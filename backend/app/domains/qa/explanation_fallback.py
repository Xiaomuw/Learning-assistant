"""
QA fallback 讲解 — 完整实现
======================
职责：
  根据检索文档、用户问题、问题类型和学习记忆，
  以"苏格拉底式助教"角色生成结构化分层讲解。

  不同 question_type 采用不同讲解风格：
    - concept  → 侧重直觉理解，多用类比
    - problem  → 侧重解题思路，不直接给答案，前两步只给方向
    - practice → 更简洁，直接给步骤
    - review   → 结合 memory.weak_points 重点强调易错点
"""

from __future__ import annotations

import re
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from app.infrastructure.llm.config import get_fallback_chat_model
from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_chat_llm
from app.infrastructure.llm.structured import invoke_with_schema


# ============================================================
# Structured Output Schema
# ============================================================

class ExplanationOutput(BaseModel):
    """QA fallback 讲解 的结构化输出"""

    topic: str = Field(
        description="本题/本问题考查的核心知识点名称",
    )
    thinking: str = Field(
        description="解题思路或概念理解的切入点，1-2 句话概述",
    )
    steps: list[str] = Field(
        description="分步骤讲解过程，每步一句话。problem 类型时前两步只给方向提示不给具体计算",
    )
    mistakes: str = Field(
        description="针对该知识点最常见的一个易错点，用一句话描述",
    )
    similar: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 个相关的知识点或题型名称，帮助学生建立知识网络",
    )


# ============================================================
# 风格指令（按 question_type 切换）
# ============================================================

STYLE_INSTRUCTIONS: dict[str, str] = {
    "concept": (
        "【讲解风格：概念理解】\n"
        "- 用直觉化、生活化的语言解释概念\n"
        "- 多使用类比和比喻帮助学生建立直观理解\n"
        "- steps 从「为什么需要这个概念」出发，逐步深入到定义和性质\n"
        "- 避免上来就列公式，先让学生'感受'到概念的意义"
    ),
    "problem": (
        "【讲解风格：解题辅导 — 苏格拉底式引导】\n"
        "- 绝对不要直接给出最终答案或完整计算过程\n"
        "- thinking 只描述「从哪个角度切入」，不透露具体方法\n"
        "- steps 的前两步只给方向性提示（如「想想这道题的已知条件暗示了什么」），\n"
        "  不写出具体计算；从第三步开始可以逐步给出更具体的指引\n"
        "- 在最后一步用反问句引导学生自己完成最后一步\n"
        "- 目标是让学生「差一步就能自己做出来」"
    ),
    "practice": (
        "【讲解风格：练习简讲】\n"
        "- 保持简洁高效，不拖泥带水\n"
        "- steps 直接给出解题步骤，每步清晰明确\n"
        "- 适合学生快速参考，不需要过多引导"
    ),
    "review": (
        "【讲解风格：复习巩固】\n"
        "- 重点关注学生的薄弱环节（下方提供了薄弱知识点列表）\n"
        "- mistakes 要特别详细，结合学生历史易错点展开\n"
        "- steps 按「回忆要点 → 澄清易混淆点 → 强化记忆」的结构组织\n"
        "- similar 优先列出与薄弱点相关的知识"
    ),
}

# 当知识库无法提供内容时，告知模型用自身通用知识回答
GENERAL_KNOWLEDGE_INSTRUCTION = """
## 当前资料来源
当前笔记本中没有此问题相关的专属资料。
请作为一名专业的教育 AI，直接使用你的通用教育知识库来讲解此问题。

重要原则：
- 请不要说"没有资料"或"无法回答"，直接给出高质量的教育回答
- 语言要清晰、概念要准确、逐步引导
- 如果学生想深入某个小节，可以在 similar 里提示相关展开方向
- 可在回答末尾提示用户上传相关资料后能获得更个性化的讲解
"""


_GENERAL_CONCEPT_MARKERS = (
    "什么是",
    "什么叫",
    "解释",
    "介绍",
    "概念",
    "define",
    "what is",
)


def _is_general_concept_question(question: str) -> bool:
    normalized = question.lower()
    return (
        "http" in normalized
        or "tcp" in normalized
        or "递归" in question
        or "数据库索引" in question
        or "tcp/ip" in normalized
        or "rag" in normalized
        or any(marker in question for marker in _GENERAL_CONCEPT_MARKERS)
        or any(marker in normalized for marker in _GENERAL_CONCEPT_MARKERS)
    )


# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT = """\
你是一位学习型 Coach 系统的主回答代理。你的目标是帮助用户理解知识，
而不是展示系统内部流程。

核心原则：
1. Notebook 是辅助上下文，不是唯一知识来源。
2. 只有 notebook_policy=strict / notebook_required=true 时，Notebook 才是必须依据。
3. 如果 notebook_required=false，即使 notebook_context 为空，也必须继续回答普通概念问题，不能因为没有 notebook 内容而拒答。
4. 如果 notebook_required=true 但 notebook_context 为空，要说明 notebook 资料不足；如补充通用解释，必须明确标注“以下不是基于 notebook”。
5. 只能使用已提供的参考资料；不要使用原始未审查检索命中。
6. 不要在最终答案中暴露“模型执行、降级回退、检索命中、检索分数”等内部状态。
7. 普通稳定概念题应直接教学讲解：先给定义，再解释机制或用途，最后给例子。

## 当前笔记本 / 知识库上下文
{notebook_context}

## 用户期望的回答风格
{user_style_instruction}

## 最近对话上下文（短期记忆）
{short_term_context}

## 当前会话摘要（中期记忆）
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

{style_instruction}

## 参考资料
以下是从知识库中检索到的相关文档，请基于这些内容进行讲解：
{context}

## 学生画像
{student_profile}

## 输出要求
{fact_answer_instruction}
请严格以 JSON 格式输出讲解内容，不包含任何其他文字，格式如下：
{{"topic": "知识点名称", "thinking": "解题思路", "steps": ["步骤1", "步骤2"], "mistakes": "易错点", "similar": ["相关知识1", "相关知识2"]}}
"""

HUMAN_PROMPT = "学生的问题：{question}"

EXPLAINER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
])


# ============================================================
# 辅助函数
# ============================================================

def _get_llm(model_name: str | None = None) -> ChatOpenAI:
    """获取当前激活聊天模型实例。"""
    return get_chat_llm(
        default_model=DEFAULT_CHAT_MODEL,
        temperature=0.3,       # 略带创造性，但保持准确
        model_override=model_name,
        timeout_seconds=18.0,
        max_retries=0,
    )


def _format_context(docs: list[dict[str, Any]]) -> str:
    """将检索文档列表拼接为上下文字符串"""
    if not docs:
        return "（暂无参考资料，请根据你的知识进行讲解）"

    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        content = doc.get("content", "")
        score = doc.get("score", 0)
        parts.append(f"[文档{i}｜相关度 {score:.2f}]\n{content}")
    return "\n\n---\n\n".join(parts)


def _is_fact_seeking_question(question: str) -> bool:
    normalized = question.lower()
    markers = (
        "是多少",
        "多少",
        "哪个",
        "哪一个",
        "默认",
        "端口",
        "是什么值",
        "什么时候",
        "在哪里",
        "谁",
        "what",
        "which",
        "default",
        "port",
    )
    return any(marker in normalized for marker in markers)


def _fact_answer_instruction(question: str, docs: list[dict[str, Any]]) -> str:
    if not docs or not _is_fact_seeking_question(question):
        return ""
    return (
        "## 事实型问题要求\n"
        "- 这是一个需要明确结论的事实型问题。\n"
        "- 如果参考资料中能支持答案，请在 thinking 或 steps[0] 里先直接给出结论，再解释依据。\n"
        "- 如果参考资料不足以支持答案，请明确说“当前 notebook 未检索到该事实”，不要只给泛泛学习建议。\n"
    )


def _split_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?；;])|\n+", text)
        if sentence.strip()
    ]


def _extract_direct_fact_from_docs(question: str, docs: list[dict[str, Any]]) -> str:
    question_lower = question.lower()
    joined_docs = "\n".join(str(doc.get("content", "") or "") for doc in docs)
    if "http" in question_lower and ("端口" in question or "port" in question_lower):
        if re.search(r"http[^。\n]{0,40}80|80[^。\n]{0,40}http", joined_docs, flags=re.IGNORECASE):
            return "HTTP 的默认端口是 80。"
        if re.search(r"https[^。\n]{0,40}443|443[^。\n]{0,40}https", joined_docs, flags=re.IGNORECASE):
            return "HTTPS 的默认端口是 443。"

    question_terms = [
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*|[\u4e00-\u9fff]{2,}", question)
        if term not in {"多少", "哪个", "哪一个", "是什么", "是多少"}
    ][:4]
    for sentence in _split_sentences(joined_docs):
        if any(term.lower() in sentence.lower() for term in question_terms):
            if re.search(r"\d+|是|为|默认|default", sentence, flags=re.IGNORECASE):
                return sentence[:180]
    return ""


def _looks_generic_fact_answer(explanation: dict[str, Any], direct_fact: str) -> bool:
    if not direct_fact:
        return False
    combined = " ".join(
        [
            str(explanation.get("thinking", "") or ""),
            " ".join(str(item) for item in explanation.get("steps", []) or []),
            str(explanation.get("mistakes", "") or ""),
        ]
    )
    if "80" in direct_fact and "80" in combined:
        return False
    if direct_fact in combined:
        return False
    generic_markers = ("检查", "回顾", "确认", "可以继续追问", "建议先", "暂无可用", "无法")
    return any(marker in combined for marker in generic_markers) or len(combined.strip()) < 60


def _enforce_fact_answer(
    *,
    question: str,
    docs: list[dict[str, Any]],
    explanation: dict[str, Any],
) -> dict[str, Any]:
    if not docs or not _is_fact_seeking_question(question):
        return explanation
    direct_fact = _extract_direct_fact_from_docs(question, docs)
    if not direct_fact:
        if _looks_generic_fact_answer(explanation, "当前 notebook 未检索到该事实"):
            return {
                **explanation,
                "thinking": "当前 notebook 未检索到足够明确的事实依据。",
                "steps": [
                    "当前 notebook 未检索到该事实。",
                    "可以补充包含该事实的资料后再问，或让我按通用知识解释。",
                ],
            }
        return explanation
    if not _looks_generic_fact_answer(explanation, direct_fact):
        return explanation
    next_steps = list(explanation.get("steps") or [])
    return {
        **explanation,
        "thinking": direct_fact,
        "steps": [
            direct_fact,
            *[step for step in next_steps if str(step).strip() and direct_fact not in str(step)],
        ][:4],
    }


def _format_student_profile(
    question_type: str,
    memory: dict[str, Any],
) -> str:
    """格式化学生画像信息"""
    weak_points = memory.get("weak_points", [])
    error_count = memory.get("error_count", {})
    recent_topics = memory.get("recent_topics", [])

    lines: list[str] = []

    if weak_points:
        lines.append(f"薄弱知识点：{', '.join(weak_points)}")
    if error_count:
        top_errors = sorted(error_count.items(), key=lambda x: x[1], reverse=True)[:5]
        errors_str = ", ".join(f"{k}(错{v}次)" for k, v in top_errors)
        lines.append(f"高频错误：{errors_str}")
    if recent_topics:
        lines.append(f"最近学习：{', '.join(recent_topics[:5])}")

    if not lines:
        lines.append("暂无历史学习数据，这可能是新学生。")

    return "\n".join(lines)


def _build_learner_context_summary(state: dict[str, Any]) -> str:
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    parts: list[str] = []

    active_topic = str(session_memory.get("active_topic") or memory.get("active_topic") or "").strip()
    if active_topic:
        parts.append(f"当前主题：{active_topic}")

    recent_topics = [
        str(item).strip()
        for item in list(memory.get("recent_topics") or session_memory.get("recent_topics") or [])
        if str(item).strip()
    ][:3]
    if recent_topics:
        parts.append(f"最近学习：{'、'.join(recent_topics)}")

    weak_points = [
        str(item).strip()
        for item in list(memory.get("weak_points") or session_memory.get("weak_points") or [])
        if str(item).strip()
    ][:3]
    if weak_points:
        parts.append(f"薄弱点：{'、'.join(weak_points)}")

    current_goal = str(session_memory.get("current_goal") or memory.get("current_goal") or "").strip()
    if current_goal:
        parts.append(f"当前目标：{current_goal}")

    return "；".join(parts)


def _apply_learner_context_to_explanation(
    explanation: dict[str, Any],
    learner_context_summary: str,
) -> dict[str, Any]:
    summary = learner_context_summary.strip()
    if not summary:
        return explanation
    steps = [
        str(item).strip()
        for item in list(explanation.get("steps") or [])
        if str(item).strip()
    ]
    hint = f"结合你的学习记录（{summary}），建议先抓住定义和使用场景，再继续区分相关概念。"
    if not any(summary in step for step in steps):
        steps = [*steps, hint][:6]
    return {**explanation, "steps": steps}


def _get_style_instruction(question_type: str) -> str:
    """根据问题类型获取对应的讲解风格指令"""
    return STYLE_INSTRUCTIONS.get(question_type, STYLE_INSTRUCTIONS["concept"])


def _format_user_style_instruction(style_name: str, style_prompt: str) -> str:
    _ = (style_name, style_prompt)
    return (
        "用户自定义风格已暂时禁用。请保持专业、自然、友好、易懂，"
        "但不要把自己说成某个虚构人物。"
    )


def _invoke_explainer_chain(payload: dict[str, Any], *, model_name: str | None = None) -> ExplanationOutput:
    """使用真正的 structured output 生成讲解结果。"""
    try:
        return invoke_with_schema(
            EXPLAINER_PROMPT,
            _get_llm(model_name),
            ExplanationOutput,
            payload,
            model_name=model_name,
        )
    except Exception as exc:
        fallback_model = get_fallback_chat_model()
        if not fallback_model or fallback_model == model_name:
            raise
        logger.warning(f"⚠️ 主讲解模型调用失败，尝试备用模型 {fallback_model}: {exc}")
        return invoke_with_schema(
            EXPLAINER_PROMPT,
            _get_llm(fallback_model),
            ExplanationOutput,
            payload,
            model_name=fallback_model,
        )


def _format_suggested_actions(retrieval_diagnosis: dict[str, Any] | None) -> list[str]:
    actions = [
        str(item).strip()
        for item in list((retrieval_diagnosis or {}).get("suggested_actions") or [])
        if str(item).strip()
    ]
    if actions:
        return actions[:3]
    return [
        "生成知识框架，先补齐章节骨架。",
        "上传 PDF 或添加 URL，让 notebook 有真实资料来源。",
        "导入题库，补充可练习和可讲解的真题解析。",
    ]


def _build_no_context_fallback(
    question: str,
    retrieval_diagnosis: dict[str, Any] | None = None,
    *,
    notebook_required: bool = False,
    search_required: bool = False,
) -> dict[str, Any]:
    normalized = question.lower()
    if notebook_required:
        return _build_notebook_insufficient_fallback(question)
    if search_required:
        return _build_search_unavailable_fallback(question)

    if _is_general_concept_question(question):
        return _build_general_knowledge_fallback(question, retrieval_diagnosis)

    diagnosis = str((retrieval_diagnosis or {}).get("diagnosis") or "")
    if diagnosis == "empty_knowledge_base":
        return {
            "topic": "知识库内容补齐",
            "thinking": "当前 notebook 暂无可用知识库内容，我不能假装已经基于资料回答。",
            "steps": [
                "当前 notebook 还没有可检索的资料块。",
                *_format_suggested_actions(retrieval_diagnosis)[:2],
            ],
            "mistakes": "知识库为空时，不要把通用回答误认为是当前 notebook 的资料结论。",
            "similar": ["知识框架", "资料入库", "RAG 检索"],
        }

    if diagnosis in {"no_matching_docs", "low_score"}:
        action = _format_suggested_actions(retrieval_diagnosis)[0]
        return {
            "topic": question[:32] or "知识库问答",
            "thinking": "当前 notebook 没有检索到足够匹配的问题资料。",
            "steps": [
                "我没有在当前 notebook 中命中能支撑这个问题的高相关内容。",
                f"建议下一步：{action}",
                "如果你希望我按通用知识解释，可以直接追问“按通用知识讲一下”。",
            ],
            "mistakes": "检索低命中时，不要把泛化解释当成当前 notebook 的专属结论。",
            "similar": ["资料覆盖", "查询改写", "知识库补齐"],
        }

    if "http" in normalized:
        return {
            "topic": "HTTP",
            "thinking": "HTTP 是浏览器、App 和服务器之间传递请求与响应的应用层协议。",
            "steps": [
                "HTTP 是浏览器和服务器之间传输网页、接口数据等内容的应用层协议。",
                "它通常采用请求-响应模式：客户端发起请求，服务器返回状态码、响应头和响应内容。",
            ],
            "mistakes": "容易把 HTTP 和 HTTPS 混淆；HTTPS 是在 HTTP 基础上加入 TLS 加密保护。",
            "similar": ["HTTPS", "请求响应模型", "状态码"],
        }
    return {
        "topic": question[:32] or "当前问题",
            "thinking": "当前 notebook 暂无可用检索资料，我先给出一版通用学习建议。",
            "steps": [
                "当前 notebook 暂无可用检索资料，建议先上传资料或生成知识框架。",
            "你也可以把问题拆成“定义、作用、例子、易错点”四部分继续追问。",
        ],
        "mistakes": "在没有参考资料时，不要把通用解释当作当前 notebook 的专属结论。",
        "similar": ["概念定义", "应用场景", "易错点辨析"],
    }


def _build_general_knowledge_fallback(
    question: str,
    retrieval_diagnosis: dict[str, Any] | None = None,
    *,
    mention_notebook: bool = False,
) -> dict[str, Any]:
    """模型调用失败时的通用知识兜底，不把 RAG 未命中误写成无法回答。"""
    normalized = question.lower()
    no_context_note = (
        "当前 notebook 未命中足够相关的资料，下面先按通用知识解释。"
        if mention_notebook
        else ""
    )
    prefix = no_context_note

    if "http" in normalized:
        return {
            "topic": "HTTP",
            "thinking": f"{prefix}HTTP 是 Web 中用于客户端和服务器通信的应用层协议。",
            "steps": [
                "HTTP 的全称是 HyperText Transfer Protocol，核心作用是在浏览器、App、服务器之间传输网页、接口数据、图片等资源。",
                "它采用请求-响应模型：客户端发送请求，服务器返回状态码、响应头和响应体。",
                "HTTP 本身是无状态协议，每次请求默认彼此独立；Cookie、Session、Token 等机制常用来补充登录态和上下文。",
                "HTTPS 不是另一个完全不同的业务协议，而是在 HTTP 上叠加 TLS 加密，用来保护传输安全。",
            ],
            "mistakes": "最常见的混淆是把 HTTP 当成传输层协议；它属于应用层，底层通常依赖 TCP 或 QUIC。",
            "similar": ["HTTPS", "状态码", "请求响应模型"],
        }

    if "tcp" in normalized:
        return {
            "topic": "TCP",
            "thinking": f"{prefix}TCP 是互联网中提供可靠字节流传输的传输层协议。",
            "steps": [
                "TCP 的全称是 Transmission Control Protocol，核心作用是在两端应用之间建立可靠、有序、面向连接的数据传输。",
                "它会通过序号、确认应答、重传、流量控制和拥塞控制，尽量保证数据不丢、不乱序、不重复交给上层应用。",
                "TCP 通常先通过三次握手建立连接，通信结束后再通过挥手过程释放连接。",
                "HTTP/1.1 和 HTTP/2 通常运行在 TCP 之上；而 HTTP/3 则基于 QUIC，不再直接依赖 TCP。",
            ],
            "mistakes": "最常见的混淆是把 TCP 当成应用层协议；TCP 属于传输层，HTTP 才是应用层协议。",
            "similar": ["三次握手", "拥塞控制", "UDP"],
        }

    if "rag" in normalized:
        return {
            "topic": "RAG",
            "thinking": f"{prefix}RAG 是把检索到的外部资料交给模型一起回答的生成方式。",
            "steps": [
                "RAG 的核心是先检索相关文档，再让模型基于这些文档生成答案。",
                "它通常包含文档切分、向量化、向量检索、上下文拼接和模型生成几个步骤。",
                "RAG 能降低模型胡编概率，但检索质量、资料覆盖度和提示词设计会直接影响答案质量。",
            ],
            "mistakes": "不要把 RAG 理解成模型自动拥有知识库；它必须先有可检索、质量足够的资料。",
            "similar": ["向量检索", "Embedding", "知识库问答"],
        }

    actions = _format_suggested_actions(retrieval_diagnosis)
    return {
        "topic": question[:32] or "当前问题",
        "thinking": prefix or "我先给你一个通用理解框架。",
        "steps": [
            "先给出概念的定义，再说明它解决什么问题。",
            "再结合一个简单例子理解它的输入、输出和使用场景。",
            f"如果需要更贴合当前 notebook 的答案，可以补充资料：{actions[0]}",
        ],
        "mistakes": "资料未命中时，要区分通用知识解释和当前 notebook 专属结论。",
        "similar": ["定义", "作用", "应用场景"],
    }


def _build_notebook_insufficient_fallback(question: str) -> dict[str, Any]:
    topic = question[:32] or "notebook 问答"
    if _is_general_concept_question(question):
        general = _build_general_knowledge_fallback(question)
        general_steps = list(general.get("steps") or [])[:3]
        return {
            "topic": str(general.get("topic") or topic),
            "thinking": (
                f"你的 notebook 里没有找到足够相关的「{topic}」内容，所以我不能按 notebook 编造解释。"
                "以下不是基于 notebook，而是通用知识讲解。"
            ),
            "steps": [
                str(general.get("thinking") or "我先给你一个通用解释。"),
                *general_steps,
            ][:6],
            "mistakes": "明确要求依据 notebook 时，不能把无关资料或通用知识伪装成资料结论。",
            "similar": list(general.get("similar") or ["资料补充", "通用解释", "关键词检索"])[:3],
        }
    return {
        "topic": topic,
        "thinking": f"你的 notebook 里没有找到足够相关的「{topic}」内容，所以我不能按 notebook 编造解释。",
        "steps": [
            "如果你希望严格依据 notebook，需要先补充或上传相关资料。",
            "如果你愿意改用通用知识，我可以直接给你讲清定义、机制和例子。",
        ],
        "mistakes": "明确要求依据 notebook 时，不能把无关资料或通用知识伪装成资料结论。",
        "similar": ["资料补充", "通用解释", "关键词检索"],
    }


def _build_search_unavailable_fallback(question: str) -> dict[str, Any]:
    return {
        "topic": question[:32] or "时效问题",
        "thinking": "这个问题依赖最新或指定来源资料，我现在不能可靠确认最新状态。",
        "steps": [
            "我可以先说明不随时间快速变化的背景知识。",
            "涉及当前版本、支持情况、价格、政策或官网原文时，需要以权威网页资料为准。",
        ],
        "mistakes": "时效问题不要凭旧知识猜最新结论。",
        "similar": ["官方文档", "版本变化", "兼容性资料"],
    }


def _build_safe_no_verified_context_fallback(question: str) -> dict[str, Any]:
    topic = question[:32] or "当前问题"
    return {
        "topic": topic,
        "thinking": "这轮暂时不能生成完整讲解，请稍后重试或换一种问法继续。",
        "steps": [
            f"你可以把「{topic}」拆成定义、作用、例子或易错点继续问。",
            "如果你希望严格依据 notebook，请补充相关资料后再问。",
        ],
        "mistakes": "没有可靠上下文时，不要把无关内容当成答案依据。",
        "similar": ["资料补充", "通用讲解", "上下文审查"],
    }


def _is_no_context_template(explanation: dict[str, Any]) -> bool:
    combined = " ".join(
        [
            str(explanation.get("thinking", "") or ""),
            " ".join(str(item) for item in explanation.get("steps", []) or []),
            str(explanation.get("mistakes", "") or ""),
        ]
    )
    markers = (
        "当前 notebook 没有检索到",
        "我没有在当前 notebook 中命中",
        "按通用知识解释",
        "补充 notebook 资料",
        "资料覆盖",
        "查询改写",
        "知识库补齐",
    )
    return any(marker in combined for marker in markers)


# ============================================================
# Agent 节点函数
# ============================================================

def explain_for_qa_fallback(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph 节点：QA fallback 讲解

    流程：
      1. 从 state 读取 question, retrieved_docs, question_type, memory
      2. 根据 question_type 选择讲解风格指令
      3. 格式化参考文档和学生画像
      4. 使用真正的 structured output 生成 ExplanationOutput
      5. 将结构化结果写入 state["explanation"]
    """
    question = str(state.get("contextual_question") or state["question"])
    question_type = state.get("question_type", "concept")
    model_name = str(state.get("model_name", "") or "").strip() or None
    if "verified_context" in state:
        docs = list(state.get("verified_context") or [])
    else:
        # Backward compatibility for older tests/callers where retrieved_docs already
        # means verified context. raw_retrieved_docs is never consumed here.
        docs = list(state.get("retrieved_docs") or [])
    memory = state.get("memory", {})
    subject_name = state.get("subject_name", "通用知识")
    retrieval_diagnosis = (
        state.get("retrieval_diagnosis")
        if isinstance(state.get("retrieval_diagnosis"), dict)
        else {}
    )
    notebook_policy = str(state.get("notebook_policy") or "skip")
    search_policy = str(state.get("search_policy") or "forbidden")
    source_policy = str(state.get("source_policy") or "none")
    notebook_required = bool(state.get("notebook_required", False) or notebook_policy == "strict")
    search_required = search_policy == "required"
    safe_no_context = bool(state.get("fallback_safe_no_context", False) and notebook_required)
    short_term_context = state.get("short_term_context", "（当前会话暂无历史上下文）")
    session_memory_context = state.get("session_memory_context", "（当前会话暂无中期摘要）")
    long_term_context = state.get("long_term_context", "（暂无长期学习记忆）")
    learner_context_summary = str(
        state.get("learner_context_summary")
        or _build_learner_context_summary(state)
        or ""
    )

    logger.info(
        f"📖 QA fallback 讲解 开始 | [{subject_name}] type={question_type} | "
        f"文档数={len(docs)} | question={question[:60]}…"
    )

    # ---- 组装 prompt 参数 ----
    style_instruction = _get_style_instruction(question_type)
    context = _format_context(docs)
    student_profile = _format_student_profile(question_type, memory)
    if learner_context_summary:
        student_profile = f"{student_profile}\n学习上下文摘要：{learner_context_summary}"
    subject_description = state.get("subject_description", "")
    user_style_name = state.get("user_style_name", "")
    user_style_prompt = state.get("user_style_prompt", "")

    if subject_name != "通用知识":
        notebook_context = f"当前知识库名称：{subject_name}。\n"
        if subject_description:
            notebook_context += f"【知识库简介】：{subject_description}\n"
        notebook_context += (
            f"notebook_required={str(notebook_required).lower()}。"
            "Notebook 是辅助上下文，不是唯一知识来源；"
            "只有 notebook_required=true 时才必须严格依据 notebook。"
        )
        if docs and retrieval_diagnosis.get("coverage_level") in {"sparse", "partial"}:
            notebook_context += "\n注意：当前 notebook 资料覆盖有限，请先基于命中资料回答，并提醒用户资料可能不完整。"
    else:
        notebook_context = (
            f"当前为通用问答模式，不限定某个专用知识库。"
            f"notebook_required={str(notebook_required).lower()}。"
        )

    user_style_instruction = _format_user_style_instruction(
        user_style_name,
        user_style_prompt,
    )

    # 判断文档来源（网络 / 知识库 / 无文档）
    web_docs = [
        d for d in docs
        if isinstance(d.get("metadata"), dict)
        and (
            d["metadata"].get("retrieval_source") == "web"
            or str(d["metadata"].get("retrieval_source") or "").startswith(("tavily", "mcp_web"))
            or bool(d["metadata"].get("url"))
            or bool(d["metadata"].get("provider"))
        )
    ]
    has_docs = bool(docs)
    is_web_sourced = bool(web_docs) and len(web_docs) >= len(docs) * 0.5

    # 语言知识类问题类型（对这些类型，模型应凭通用知识回答）
    knowledge_types = {"concept", "problem", "review", "mcq_problem", "practice"}
    can_use_general_knowledge = question_type in knowledge_types

    if not has_docs and notebook_required:
        return {"explanation": _build_notebook_insufficient_fallback(question)}

    if not has_docs and search_required:
        return {"explanation": _build_search_unavailable_fallback(question)}

    if not has_docs and safe_no_context:
        return {"explanation": _build_safe_no_verified_context_fallback(question)}

    if not has_docs:
        # 无任何文档时：
        # 如果是知识类问题，让模型凭自身知识回答（不应是“无法回答”的敎袋）
        if can_use_general_knowledge:
            logger.info(
                f"📖 无知识库文档，模型将凭通用知识回答 | type={question_type}"
            )
            # 将通用知识指令注入为特殊上下文
            context = GENERAL_KNOWLEDGE_INSTRUCTION
            # 不限制 notebook，打开全局知识视野
            notebook_context = "(此问题将凭通用教育知识回答，不限定于特定 notebook)"
        else:
            # 无知识库 + 非知识类，才展示引导补充资料的 fallback
            return {
                "explanation": _build_no_context_fallback(
                    question,
                    retrieval_diagnosis,
                    notebook_required=notebook_required,
                    search_required=search_required,
                )
            }

    elif is_web_sourced:
        # 文档主要来自外部网络
        logger.info(f"🌐 使用网络搜索结果作为上下文 | doc数={len(docs)}")
        notebook_context = (
            "当前问题依赖外部网页/来源资料。"
            "请基于已提供的网络搜索结果回答；必要时列出来源名称，"
            "但不要暴露搜索工具、检索分数或内部降级状态。"
        )
    elif source_policy == "notebook":
        notebook_context += "\n如果使用参考资料回答，必须说明“根据你的 notebook/资料”。"

    try:
        result = _invoke_explainer_chain({
            "style_instruction": style_instruction,
            "context": context,
            "student_profile": student_profile,
            "notebook_context": notebook_context,
            "user_style_instruction": user_style_instruction,
            "fact_answer_instruction": _fact_answer_instruction(question, docs),
            "short_term_context": short_term_context,
            "session_memory_context": session_memory_context,
            "long_term_context": long_term_context,
            "question": question,
        }, model_name=model_name)
        explanation = result.model_dump()
        if not docs and can_use_general_knowledge and _is_no_context_template(explanation):
            logger.info("📖 模型返回资料不足模板，已替换为通用知识兜底回答")
            explanation = _build_general_knowledge_fallback(
                question,
                retrieval_diagnosis,
                mention_notebook=_should_mention_notebook_miss(subject_name, retrieval_diagnosis),
            )
        explanation = _enforce_fact_answer(question=question, docs=docs, explanation=explanation)
        explanation = _apply_learner_context_to_explanation(explanation, learner_context_summary)
        if docs and retrieval_diagnosis.get("coverage_level") in {"sparse", "partial"}:
            steps = list(explanation.get("steps") or [])
            coverage_note = "提示：当前 notebook 资料覆盖有限，以上回答优先基于已命中的资料。"
            if not any(coverage_note in str(step) for step in steps):
                explanation["steps"] = [*steps, coverage_note][:6]

        logger.info(
            f"📖 讲解完成 | 知识点={explanation['topic']} | "
            f"步骤数={len(explanation['steps'])} | "
            f"易错点={explanation['mistakes'][:40]}…"
        )

    except Exception as e:
        logger.error(f"❌ QA fallback 讲解 调用失败: {e}")
        model_unavailable_reason = _model_unavailable_reason(e)
        if is_web_sourced and can_use_general_knowledge:
            explanation = _build_general_knowledge_fallback(question, retrieval_diagnosis)
            base_thinking = str(explanation.get("thinking", "") or "")
            explanation["thinking"] = (
                f"根据网络补充资料和稳定背景知识，我先给出简版：{base_thinking}"
                if base_thinking
                else "根据网络补充资料，我先给出一个简版结论。"
            )
            explanation = _apply_learner_context_to_explanation(explanation, learner_context_summary)
            return {
                "explanation": explanation,
                "learner_context_summary": learner_context_summary,
                "model_unavailable_reason": model_unavailable_reason,
            }

        if docs:
            top_doc = str(docs[0].get("content", "")).strip()
            excerpt = top_doc[:420] + ("..." if len(top_doc) > 420 else "")
            direct_fact = _extract_direct_fact_from_docs(question, docs)
            if source_policy == "notebook":
                thinking = direct_fact or "根据你的 notebook，我先整理出和问题最相关的要点。"
                first_step = direct_fact or f"根据你的 notebook，最相关内容可以概括为：{excerpt}"
            elif source_policy in {"web", "mixed"} or is_web_sourced:
                thinking = direct_fact or "根据可用的网页资料，我先整理出一个简版结论。"
                first_step = direct_fact or f"相关来源要点可以概括为：{excerpt}"
            else:
                thinking = direct_fact or "我先根据可用资料整理出一个简版结论。"
                first_step = direct_fact or f"相关资料要点可以概括为：{excerpt}"
            explanation = {
                "topic": question[:32] or "知识库问答",
                "thinking": thinking,
                "steps": [
                    first_step,
                    "你可以继续追问某个术语或要求我按步骤展开。"
                ],
                "mistakes": "注意区分资料原文能支持的结论和额外推断，资料不足时不要硬推。",
                "similar": ["概念定义", "应用场景", "相关资料"],
            }
            explanation = _apply_learner_context_to_explanation(explanation, learner_context_summary)
            return {
                "explanation": explanation,
                "learner_context_summary": learner_context_summary,
                "model_unavailable_reason": model_unavailable_reason,
            }

        if can_use_general_knowledge:
            explanation = _build_general_knowledge_fallback(
                question,
                retrieval_diagnosis,
                mention_notebook=_should_mention_notebook_miss(subject_name, retrieval_diagnosis),
            )
        else:
            explanation = _build_no_context_fallback(
                question,
                retrieval_diagnosis,
                notebook_required=notebook_required,
                search_required=search_required,
            )
        explanation = _apply_learner_context_to_explanation(explanation, learner_context_summary)

    return {
        "explanation": explanation,
        "learner_context_summary": learner_context_summary,
        "model_unavailable_reason": locals().get("model_unavailable_reason", ""),
    }


def _should_mention_notebook_miss(subject_name: str, retrieval_diagnosis: dict[str, Any] | None) -> bool:
    diagnosis = retrieval_diagnosis if isinstance(retrieval_diagnosis, dict) else {}
    return subject_name != "通用知识" and bool(diagnosis.get("diagnosis"))


def _model_unavailable_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "401" in message or "unauthorized" in message or "subscription tier" in message or "not available" in message:
        return "unauthorized_model"
    return ""
