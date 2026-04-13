"""
检索 Agent — 完整实现
======================
职责：
  1. 从 state 取出 question，调用 Chroma 向量检索 top-5
  2. 用 LangChain structured output 对每个文档打相关性分 (0.0~1.0)
     打分 schema: { doc_id: str, score: float, reason: str }
  3. 过滤掉分数低于 0.5 的文档
  4. 如果过滤后文档数为 0 或最高分 < 0.6：
     - LLM 重写问题（去掉具体数字，保留核心概念）
     - 用重写后的问题重新检索
     - 标记 is_rewritten = True
  5. 返回更新后的 state: retrieved_docs + is_rewritten
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from schemas.state import AgentState
from tools.model_provider import get_chat_llm, get_embeddings


# ============================================================
# Structured Output Schema
# ============================================================

class DocRelevanceScore(BaseModel):
    """单个文档的相关性打分结果"""
    doc_id: str = Field(description="文档的唯一标识")
    score: float = Field(
        ge=0.0, le=1.0,
        description="该文档与用户问题的相关性分数，0.0 完全不相关，1.0 完全匹配",
    )
    reason: str = Field(description="给出该分数的简要理由")


class DocScoreList(BaseModel):
    """批量打分结果（一次性对多个文档打分）"""
    scores: list[DocRelevanceScore] = Field(
        description="每个文档的相关性打分列表"
    )


class RewrittenQuery(BaseModel):
    """重写后的检索查询"""
    rewritten_query: str = Field(
        description="重写后的查询语句，去掉具体数字，保留核心概念和知识点"
    )
    removed_details: list[str] = Field(
        description="被移除或泛化的具体细节列表（如具体数字、特定条件等）"
    )
    core_concepts: list[str] = Field(
        description="保留下来的核心概念和知识点关键词"
    )


# ============================================================
# Prompt 模板
# ============================================================

SCORE_SYSTEM_PROMPT = """\
你是一个文档相关性评估专家。请对用户问题和一组检索到的文档逐一打分。

评分标准：
- 0.0 ~ 0.3：完全不相关，或仅有少量词汇重合
- 0.3 ~ 0.5：部分相关但缺乏关键信息，不足以回答问题
- 0.5 ~ 0.7：相关，包含部分有用信息，可作为辅助参考
- 0.7 ~ 0.9：高度相关，包含回答问题所需的关键信息
- 0.9 ~ 1.0：直接回答了用户问题，信息精准完整

用户问题：{question}

以下是检索到的文档，请逐一打分：
{documents}
"""

SCORE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SCORE_SYSTEM_PROMPT),
    ("human", '请对上述每个文档给出 doc_id、score 和 reason。严格以 JSON 格式输出，不包含任何其他文字：\n{{"scores": [{{"doc_id": "xxx", "score": 0.8, "reason": "理由"}}, ...]}}'),
])

REWRITE_SYSTEM_PROMPT = """\
你是一个搜索查询改写专家。用户的原始问题在向量库中检索效果不佳，\
需要你将问题改写得更通用以提高召回率。

改写原则：
1. 去掉具体数字（如"3个""第二题""2024年"）
2. 去掉过于具体的条件（如"已知 a=5, b=3"）
3. 保留核心概念和知识点名称
4. 用更通用、教科书式的表述替代口语化表达
5. 不改变问题的核心意图

示例：
- "二次函数 y=2x²+3x-5 的顶点坐标怎么求" → "二次函数顶点坐标求法"
- "已知三角形三边为3,4,5，求面积" → "已知三角形三边长求面积的方法"
"""

REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", REWRITE_SYSTEM_PROMPT),
    ("human", '原始问题：{question}\n请改写为更通用的检索查询。严格以 JSON 格式输出，不包含任何其他文字：\n{{"rewritten_query": "重写后查询", "removed_details": ["被移除的细节"], "core_concepts": ["核心概念"]}}'),
])


# ============================================================
# 辅助函数
# ============================================================

def _get_llm() -> ChatOpenAI:
    """获取 gpt-4o-mini 实例"""
    return get_chat_llm(
        default_model="openai-gpt-4o-mini",
        temperature=0,
    )


def _get_vectorstore(subject_id: str | None = None) -> Chroma:
    """获取 LangChain Chroma 向量库实例，配置从环境变量读取"""
    from tools.retriever import get_chroma_client
    embedding = get_embeddings(default_model="openai-text-embedding-3-small")
    collection_name = (
        f"learning_{subject_id}" if subject_id
        else os.getenv("CHROMA_COLLECTION_NAME", "learning_docs")
    )
    return Chroma(
        client=get_chroma_client(),
        collection_name=collection_name,
        embedding_function=embedding,
    )


# ============================================================
# 核心：向量检索
# ============================================================

def _retrieve_from_chroma(
    query: str,
    top_k: int = 5,
    subject_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    从 Chroma 向量库检索 top-k 文档。
    使用 Chroma 内置 embedding（无需外部 API）。

    Returns:
        [{ "doc_id": str, "content": str, "metadata": dict }, ...]
    """
    # 空库时跳过检索
    from tools.retriever import get_collection
    collection = get_collection(subject_id=subject_id)
    if collection.count() == 0:
        logger.info(f"🔍 知识库为空 (subject={subject_id or 'default'})，跳过向量检索")
        return []

    # 直接使用 Chroma collection.query()（内置 embedding）
    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    docs: list[dict[str, Any]] = []
    if results and results.get("documents"):
        for i, doc_text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            distance = results["distances"][0][i] if results.get("distances") else 0.5
            doc_id = results["ids"][0][i] if results.get("ids") else str(uuid.uuid4())[:8]
            docs.append({
                "doc_id": doc_id[:8],
                "content": doc_text,
                "metadata": meta,
                "distance": distance,
            })

    logger.info(f"🔍 Chroma 检索完成: query='{query[:50]}…', 召回 {len(docs)} 篇")
    return docs


# ============================================================
# 核心：LLM 批量打分
# ============================================================

def _format_docs_for_scoring(docs: list[dict[str, Any]]) -> str:
    """将文档列表格式化为可供 LLM 打分的文本"""
    parts: list[str] = []
    for doc in docs:
        truncated = doc["content"][:1500]  # 截断，避免 token 溢出
        parts.append(f"[doc_id={doc['doc_id']}]\n{truncated}")
    return "\n\n---\n\n".join(parts)


def _score_documents(
    question: str,
    docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    用 LLM structured output 批量对文档打相关性分。
    将打分结果合并回每个 doc 的 score / reason 字段。
    """
    if not docs:
        return []

    llm = _get_llm()
    chain = SCORE_PROMPT | llm

    try:
        response = chain.invoke({
            "question": question,
            "documents": _format_docs_for_scoring(docs),
        })
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)

        # 建立 doc_id → score 映射
        score_map = {}
        for s in data.get("scores", []):
            score_map[s["doc_id"]] = s

        for doc in docs:
            matched = score_map.get(doc["doc_id"])
            if matched:
                doc["score"] = round(float(matched.get("score", 0.4)), 4)
                doc["reason"] = matched.get("reason", "")
            else:
                logger.warning(f"⚠️ doc_id={doc['doc_id']} 未获得打分，默认 0.4")
                doc["score"] = 0.4
                doc["reason"] = "未获得 LLM 打分"

        logger.info(
            f"📊 打分完成: "
            + ", ".join(f"{d['doc_id']}={d['score']:.2f}" for d in docs)
        )

    except Exception as e:
        logger.error(f"❌ LLM 批量打分失败: {e}")
        # 全部使用基于向量距离的启发式分数
        for doc in docs:
            heuristic = max(0.0, 1.0 - doc.get("distance", 0.5))
            doc["score"] = round(heuristic, 4)
            doc["reason"] = "LLM 打分失败，使用向量距离估算"

    # 按 score 降序
    docs.sort(key=lambda d: d["score"], reverse=True)
    return docs


# ============================================================
# 核心：LLM 重写查询
# ============================================================

def _rewrite_query(question: str) -> str:
    """用 LLM 将原始问题改写为更通用的检索查询"""
    llm = _get_llm()
    chain = REWRITE_PROMPT | llm

    try:
        response = chain.invoke({"question": question})
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        rewritten = data.get("rewritten_query", question)
        logger.info(
            f"✏️ 查询重写完成:\n"
            f"   原始: {question[:60]}…\n"
            f"   重写: {rewritten}\n"
            f"   移除: {data.get('removed_details', [])}\n"
            f"   保留: {data.get('core_concepts', [])}"
        )
        return rewritten
    except Exception as e:
        logger.error(f"❌ 查询重写失败，使用原始问题: {e}")
        return question


# ============================================================
# 过滤 & 判断
# ============================================================

FILTER_THRESHOLD = 0.5    # 过滤掉低于此分数的文档
REWRITE_THRESHOLD = 0.6   # 最高分低于此值 → 触发重写


def _filter_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤掉分数低于 FILTER_THRESHOLD 的文档"""
    filtered = [d for d in docs if d.get("score", 0) >= FILTER_THRESHOLD]
    removed = len(docs) - len(filtered)
    if removed:
        logger.info(f"🗑️ 过滤掉 {removed} 篇低分文档 (score < {FILTER_THRESHOLD})")
    return filtered


def _needs_rewrite(filtered_docs: list[dict[str, Any]]) -> bool:
    """判断是否需要重写查询"""
    if len(filtered_docs) == 0:
        logger.info("🔄 过滤后无文档，需要重写查询")
        return True

    max_score = max(d.get("score", 0) for d in filtered_docs)
    if max_score < REWRITE_THRESHOLD:
        logger.info(
            f"🔄 最高分 {max_score:.2f} < {REWRITE_THRESHOLD}，需要重写查询"
        )
        return True

    return False


# ============================================================
# 清理输出
# ============================================================

def _clean_docs_for_state(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清理文档字段，只保留 state 需要的 content / metadata / score"""
    return [
        {
            "content": d["content"],
            "metadata": d.get("metadata", {}),
            "score": d["score"],
        }
        for d in docs
    ]


# ============================================================
# 记忆→检索 反馈环路（架构图虚线：历史）
# ============================================================

def _enrich_query_with_memory(
    question: str,
    memory: dict[str, Any],
) -> str:
    """
    利用学习记忆增强检索查询。

    将 recent_topics 和 weak_points 中与问题可能相关的关键词
    附加到查询中，帮助向量检索理解学科上下文。

    Args:
        question: 用户原始问题
        memory: state 中的 memory 字段

    Returns:
        增强后的查询字符串（原始问题 + 上下文关键词）
    """
    if not memory:
        return question

    context_parts: list[str] = []

    # 最近学习的知识点（取最近 3 个作为上下文）
    recent = memory.get("recent_topics", [])
    if recent:
        context_parts.append("相关知识点: " + ", ".join(recent[:3]))

    # 薄弱知识点（可能是用户反复问的领域）
    weak = memory.get("weak_points", [])
    if weak:
        context_parts.append("薄弱领域: " + ", ".join(weak[:3]))

    if not context_parts:
        return question

    enriched = f"{question}\n[学习上下文] {'; '.join(context_parts)}"
    logger.debug(f"🧠 查询增强: '{question[:40]}…' → 附加 {len(context_parts)} 段上下文")
    return enriched


# ============================================================
# Agent 节点函数
# ============================================================

def retriever_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：检索 Agent

    完整流程：
      1. 用原始 question 从 Chroma 检索 top-5
      2. LLM structured output 批量打分 { doc_id, score, reason }
      3. 过滤 score < 0.5 的文档
      4. 如果过滤后为空 或 最高分 < 0.6：
         a. LLM 重写 question（去数字，留概念）
         b. 用重写后的 query 重新检索 + 打分 + 过滤
         c. 标记 is_rewritten = True
      5. 返回 { retrieved_docs, is_rewritten }
    """
    question = state["question"]
    memory = state.get("memory", {})
    subject_id = state.get("subject_id")
    subject_name = state.get("subject_name", "通用")
    logger.info(f"🔍 检索 Agent 开始: [{subject_name}] {question[:80]}…")

    # ---- 利用学习记忆增强检索（架构图：记忆→检索 反馈环路） ----
    enriched_query = _enrich_query_with_memory(question, memory)

    # ---- 第一轮：增强后的问题检索 ----
    raw_docs = _retrieve_from_chroma(query=enriched_query, top_k=5, subject_id=subject_id)
    scored_docs = _score_documents(question=question, docs=raw_docs)
    filtered_docs = _filter_docs(scored_docs)

    is_rewritten = False

    # ---- 判断是否需要重写 ----
    if _needs_rewrite(filtered_docs):
        is_rewritten = True

        # 重写查询
        rewritten_query = _rewrite_query(question)

        # 第二轮：重写后的查询检索
        rewrite_raw = _retrieve_from_chroma(query=rewritten_query, top_k=5, subject_id=subject_id)
        rewrite_scored = _score_documents(
            question=question,  # 打分仍用原始问题衡量相关度
            docs=rewrite_raw,
        )
        filtered_docs = _filter_docs(rewrite_scored)

        logger.info(f"🔄 重写后检索得到 {len(filtered_docs)} 篇有效文档")
    else:
        logger.info(f"✅ 第一轮检索质量良好，共 {len(filtered_docs)} 篇有效文档")

    # ---- 清理 & 输出 ----
    retrieved_docs = _clean_docs_for_state(filtered_docs)

    top_score = retrieved_docs[0]["score"] if retrieved_docs else 0.0
    logger.info(
        f"🔍 检索完成 | 文档数={len(retrieved_docs)} | "
        f"最高分={top_score:.2f} | 重写={is_rewritten}"
    )

    return {
        "retrieved_docs": retrieved_docs,
        "is_rewritten": is_rewritten,
    }
