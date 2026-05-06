"""
QA fallback 检索 — 完整实现
======================
职责：
  1. 从 state 取出 question，调用 PGVector 检索 top-5
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

import uuid
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_chat_llm
from app.infrastructure.llm.profile import get_model_profile
from app.infrastructure.llm.structured import invoke_with_schema
from app.services.rag.query_policy import build_contextual_query
from app.services.rag.retriever import diagnose_retrieval, filter_relevant_documents, retrieve
from app.shared.schemas.contracts import RetrievedDocument


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

## 最近对话上下文（短期记忆）
{short_term_context}

## 当前会话摘要（中期记忆）
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

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

## 最近对话上下文（短期记忆）
{short_term_context}

## 当前会话摘要（中期记忆）
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

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

def _get_llm(model_name: str | None = None) -> ChatOpenAI:
    """获取当前激活聊天模型实例。"""
    return get_chat_llm(
        default_model=DEFAULT_CHAT_MODEL,
        temperature=0,
        model_override=model_name,
    )


def _invoke_score_chain(
    question: str,
    documents: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
) -> DocScoreList:
    """使用 LangChain structured output 对召回文档批量打分。"""
    llm = _get_llm(model_name)
    return invoke_with_schema(
        SCORE_PROMPT,
        llm,
        DocScoreList,
        {
            "question": question,
            "documents": documents,
            "short_term_context": short_term_context,
            "session_memory_context": session_memory_context,
            "long_term_context": long_term_context,
        },
        model_name=model_name,
    )


def _invoke_rewrite_chain(
    question: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
) -> RewrittenQuery:
    """使用 LangChain structured output 重写低质量检索查询。"""
    llm = _get_llm(model_name)
    return invoke_with_schema(
        REWRITE_PROMPT,
        llm,
        RewrittenQuery,
        {
            "question": question,
            "short_term_context": short_term_context,
            "session_memory_context": session_memory_context,
            "long_term_context": long_term_context,
        },
        model_name=model_name,
    )


# ============================================================
# 核心：向量检索
# ============================================================

def _retrieve_documents(
    query: str,
    top_k: int = 5,
    subject_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    从当前 notebook 的 PGVector collection 检索 top-k 文档。

    Returns:
        [{ "doc_id": str, "content": str, "metadata": dict }, ...]
    """
    # 空库时跳过检索
    docs = [
        doc.model_dump()
        for doc in retrieve(query=query, top_k=top_k, subject_id=subject_id, user_id=user_id)
    ]
    if not docs:
        logger.info(f"🔍 知识库为空 (subject={subject_id or 'default'})，跳过向量检索")
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
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    用 LLM structured output 批量对文档打相关性分。
    将打分结果合并回每个 doc 的 score / reason 字段。
    """
    if not docs:
        return []

    if model_name and not get_model_profile(model_name).supports_structured_output:
        for doc in docs:
            fallback_score = doc.get("score", max(0.0, 1.0 - doc.get("distance", 0.5)))
            doc["score"] = round(float(fallback_score), 4)
            doc["reason"] = "当前模型不支持结构化打分，使用向量检索分数"
        docs.sort(key=lambda d: d["score"], reverse=True)
        return docs

    try:
        result = _invoke_score_chain(
            question=question,
            documents=_format_docs_for_scoring(docs),
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )

        # 建立 doc_id → score 映射
        score_map = {}
        for score in result.scores:
            score_map[score.doc_id] = score

        for doc in docs:
            matched = score_map.get(doc["doc_id"])
            if matched:
                doc["score"] = round(float(matched.score), 4)
                doc["reason"] = matched.reason
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

def _rewrite_query(
    question: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
) -> str:
    """用 LLM 将原始问题改写为更通用的检索查询"""
    if model_name and not get_model_profile(model_name).supports_structured_output:
        logger.info("✏️ 当前模型不支持结构化查询改写，使用原始问题")
        return question

    try:
        result = _invoke_rewrite_chain(
            question=question,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )
        rewritten = result.rewritten_query or question
        logger.info(
            f"✏️ 查询重写完成:\n"
            f"   原始: {question[:60]}…\n"
            f"   重写: {rewritten}\n"
            f"   移除: {result.removed_details}\n"
            f"   保留: {result.core_concepts}"
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


def _diagnose_retrieved_docs(
    *,
    query: str,
    docs: list[dict[str, Any]],
    subject_id: str | None,
) -> dict[str, Any]:
    retrieved_documents = [RetrievedDocument.model_validate(doc) for doc in docs]
    return diagnose_retrieval(
        query=query,
        docs=retrieved_documents,
        subject_id=subject_id,
        min_ready_score=FILTER_THRESHOLD,
    ).model_dump()


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

def retrieve_for_qa_fallback(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph 节点：QA fallback 检索

    完整流程：
      1. 用原始 question 从 PGVector 检索 top-5
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
    short_term_messages = state.get("short_term_messages", [])
    short_term_context = state.get("short_term_context", "（当前会话暂无历史上下文）")
    session_memory = state.get("session_memory", {})
    session_memory_context = state.get("session_memory_context", "（当前会话暂无中期摘要）")
    long_term_context = state.get("long_term_context", "（暂无长期学习记忆）")
    model_name = str(state.get("model_name", "") or "").strip() or None
    subject_id = state.get("subject_id")
    user_id = str(state.get("user_id") or "").strip() or None
    subject_name = state.get("subject_name", "通用")
    logger.info(f"🔍 QA fallback 检索 开始: [{subject_name}] {question[:80]}…")

    contextual_query = build_contextual_query(question, short_term_messages, session_memory, memory)
    if contextual_query != question:
        logger.info(
            f"🧭 上下文补全查询: 原始='{question[:40]}…' → 补全='{contextual_query[:80]}…'"
        )

    # ---- 利用短期 / 长期记忆增强检索（记忆→检索反馈环路） ----
    enriched_query = _enrich_query_with_memory(contextual_query, memory)

    # ---- 第一轮：增强后的问题检索 ----
    raw_docs = _retrieve_documents(query=enriched_query, top_k=5, subject_id=subject_id, user_id=user_id)
    scored_docs = _score_documents(
        question=contextual_query,
        docs=raw_docs,
        short_term_context=short_term_context,
        session_memory_context=session_memory_context,
        long_term_context=long_term_context,
        model_name=model_name,
    )
    filtered_docs = _filter_docs(scored_docs)

    is_rewritten = False

    # ---- 判断是否需要重写 ----
    if _needs_rewrite(filtered_docs):
        is_rewritten = True

        # 重写查询
        rewritten_query = _rewrite_query(
            question=contextual_query,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )

        # 第二轮：重写后的查询检索
        rewrite_raw = _retrieve_documents(query=rewritten_query, top_k=5, subject_id=subject_id, user_id=user_id)
        rewrite_scored = _score_documents(
            question=contextual_query,
            docs=rewrite_raw,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )
        filtered_docs = _filter_docs(rewrite_scored)

        logger.info(f"🔄 重写后检索得到 {len(filtered_docs)} 篇有效文档")
    else:
        logger.info(f"✅ 第一轮检索质量良好，共 {len(filtered_docs)} 篇有效文档")

    # ---- Context Audit：fallback 也只能输出 verified context ----
    raw_retrieved_docs = _clean_docs_for_state(filtered_docs)
    typed_raw_docs = [
        doc
        for doc in (RetrievedDocument.model_validate(item) for item in raw_retrieved_docs)
    ]
    verified_typed_docs, relevance = filter_relevant_documents(
        query=contextual_query,
        docs=typed_raw_docs,
        threshold=0.70,
    )
    retrieved_docs = [doc.model_dump() for doc in verified_typed_docs]
    raw_count = len(raw_retrieved_docs)
    verified_count = len(retrieved_docs)
    top_score = float(relevance.get("top_score") or 0.0)
    reason = str(relevance.get("reason", "") or "")
    if verified_count:
        decision = "keep"
        usable = True
        audit_reason = "verified_context_ready"
        score = max(0.70, top_score)
    else:
        decision = "discard"
        usable = False
        audit_reason = "no_core_entity_overlap" if reason == "no_core_term_overlap" else reason or "low_relevance"
        score = 0.0
    context_audit = {
        "usable": usable,
        "score": round(score, 4),
        "decision": decision,
        "reason": audit_reason,
        "matched_terms": [],
        "missing_terms": list(relevance.get("key_terms") or []),
        "can_answer_question": usable,
        "raw_count": raw_count,
        "verified_count": verified_count,
        "discarded_count": max(0, raw_count - verified_count),
    }
    retrieval_diagnosis = _diagnose_retrieved_docs(
        query=contextual_query,
        docs=retrieved_docs,
        subject_id=subject_id,
    )

    top_score = retrieved_docs[0]["score"] if retrieved_docs else 0.0
    logger.info(
        f"🔍 检索完成 | 文档数={len(retrieved_docs)} | "
        f"最高分={top_score:.2f} | 重写={is_rewritten} | "
        f"诊断={retrieval_diagnosis.get('diagnosis')}"
    )

    return {
        "raw_retrieved_docs": raw_retrieved_docs,
        "verified_context": retrieved_docs,
        "retrieved_docs": retrieved_docs,
        "notebook_retrieved": bool(raw_retrieved_docs),
        "notebook_context": "\n\n".join(
            str(doc.get("content", "") or "").strip()
            for doc in retrieved_docs
            if str(doc.get("content", "") or "").strip()
        ),
        "context_audit": context_audit,
        "retrieval_relevance": relevance,
        "is_rewritten": is_rewritten,
        "contextual_query": contextual_query,
        "retrieval_diagnosis": retrieval_diagnosis,
    }
