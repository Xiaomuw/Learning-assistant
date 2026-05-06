"""
路由 Agent — 完整实现
======================
职责：分析用户问题，判断 question_type。

使用 LangChain structured output + Pydantic BaseModel
让 LLM 输出固定分类枚举及置信度，低置信度时回退为 concept。

分类标签：
  - concept   : 概念理解类（"什么是xxx"、"解释xxx"、"怎么理解"）
  - problem   : 解题求助类（发来一道具体题目要求解答）
  - practice  : 练习出题类（"给我出几道题"、"我要练习"）
  - review    : 复习巩固类（"帮我复习"、"我哪里错了"、"薄弱点"）
  - meta      : 助手元问题（"你是什么模型"、"你是谁"、"你能做什么"）
  - smalltalk : 寒暄闲聊（"你好"、"在吗"、"hi"、"早上好"）
  - mcq_problem: 用户贴来一道带 A/B/C/D 选项的选择题，想让助手判题或讲解
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from app.shared.schemas.state import AgentState
from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_chat_llm
from app.infrastructure.llm.structured import invoke_with_schema


# ============================================================
# Structured Output Schema
# ============================================================

class QuestionType(str, Enum):
    """问题类型枚举"""
    CONCEPT = "concept"
    PROBLEM = "problem"
    PRACTICE = "practice"
    REVIEW = "review"
    META = "meta"
    SMALLTALK = "smalltalk"
    MCQ_PROBLEM = "mcq_problem"


class RouteType(str, Enum):
    """执行路线枚举"""

    FAST = "fast"
    EXPLAIN = "explain"
    RAG = "rag"
    AGENT = "agent"


class NotebookPolicy(str, Enum):
    SKIP = "skip"
    OPTIONAL = "optional"
    REQUIRED = "required"
    STRICT = "strict"


class SearchPolicy(str, Enum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    REQUIRED = "required"


class SourcePolicy(str, Enum):
    NONE = "none"
    NOTEBOOK = "notebook"
    WEB = "web"
    MIXED = "mixed"


class RouterOutput(BaseModel):
    """路由 Agent 的结构化输出"""

    question_type: QuestionType = Field(
        description=(
            "用户问题的分类标签。"
            "concept: 概念理解类；"
            "problem: 解题求助类；"
            "practice: 练习出题类；"
            "review: 复习巩固类；"
            "meta: 询问助手/模型/能力/当前知识库等元问题；"
            "smalltalk: 寒暄、打招呼、确认是否在线等闲聊；"
            "mcq_problem: 带有 A/B/C/D 选项的选择题判题或讲题请求。"
        )
    )

    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="对该分类结果的置信度，范围 0.0 ~ 1.0",
    )

    route: RouteType = Field(
        default=RouteType.EXPLAIN,
        description=(
            "本轮执行路线。fast: 极简单/元问题/寒暄；"
            "explain: 普通教学讲解；rag: 需要当前 notebook/资料库；"
            "agent: 需要外部搜索、工具或最新信息。"
        ),
    )

    route_confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="对执行路线判断的置信度，范围 0.0 ~ 1.0",
    )

    notebook_policy: NotebookPolicy = Field(
        default=NotebookPolicy.SKIP,
        description=(
            "是否使用 notebook。skip: 不检索；optional: 可检索但低相关丢弃；"
            "required: 用户希望优先参考 notebook，但资料不足时可补充通用知识；"
            "strict: 用户明确要求只依据 notebook，低相关时不能编造。"
        ),
    )

    search_policy: SearchPolicy = Field(
        default=SearchPolicy.FORBIDDEN,
        description=(
            "是否使用外部搜索。forbidden: 禁止；allowed: 可在必要时搜索；"
            "required: 最新/官网/来源类问题必须搜索。"
        ),
    )

    source_policy: SourcePolicy = Field(
        default=SourcePolicy.NONE,
        description="最终回答的来源约束：none/notebook/web/mixed。",
    )

    reasoning: str = Field(
        description="简要说明判断理由（一两句话）",
    )


# ============================================================
# Prompt
# ============================================================

ROUTER_SYSTEM_PROMPT = """\
你是一个学习问题路由专家。请根据用户的问题，同时判断问题意图 question_type \
和执行路线 route，并给出置信度与简要理由。

## 最近对话上下文（短期记忆）
{short_term_context}

## 当前会话摘要（中期记忆）
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

## 上一轮问题类型（上下文感知）
{last_question_type_hint}

## 前置学习策略
{learning_context_hint}

## 分类标签及判断规则

### concept（概念理解类）
用户在询问定义、原理、概念解释。
典型特征：问"为什么""是什么""怎么理解""什么叫做""原理是什么""概念"

### problem（解题求助类）
用户发来一道具体题目，希望得到解答或解题过程。
典型特征：包含具体的数学公式、化学方程式、物理题目、编程题、\
阅读理解题等需要"解"的内容；出现"这道题""求解""计算""证明"

### mcq_problem（选择题判题类）
用户直接贴来一道带 A/B/C/D 选项的题，希望判断正确答案或讲解选项。
典型特征：同一条消息里出现题干与 A. / B. / C. / D. 四个选项；\
或明确要求"这道选择题选什么""帮我判断 A/B/C/D 哪个对"

### practice（练习出题类）
用户请求系统生成练习题来做。
典型特征："出几道题""我要练习""来点题目""给我出题""再来一道""做题"

### review（复习巩固类）
用户想要复习已学内容、查看自己的薄弱点或错题。
典型特征："复习""总结一下""我哪里错了""薄弱点""回顾""帮我整理"

### meta（助手元问题）
用户在询问助手本身的信息，而不是某个学科知识点。
典型特征："你是什么模型""你是谁""你能做什么""当前用的什么模型""当前知识库是什么"

### smalltalk（寒暄闲聊）
用户只是打招呼、寒暄、确认助手是否在线，尚未进入具体学习问题。
典型特征："你好""hi""hello""在吗""早上好""晚上好""嗨"

## 执行路线 route

### fast
极简单问题、寒暄、助手元问题、只需要一句轻量回答的问题。不要调用资料库或外部工具。

### explain
普通概念讲解、解题引导、复习讲解。模型优先回答；如果 search_policy=allowed，可在确有需要时搜索。

### rag
用户希望参考当前 notebook、知识库、资料、PDF、文档、笔记、上传内容回答；或当前处于具体 notebook 下的学习问答。

### agent
用户明确要求搜索、联网、查最新信息、调用外部工具、查询 API/系统状态，或问题本身依赖实时外部信息。

## 策略字段

- 通用稳定概念题（如“什么是 HTTP”）：route=explain, notebook_policy=skip, search_policy=allowed，但不要默认搜索
- 明确说“根据/依据/当前 notebook/PDF/资料/上传内容”：route=rag, notebook_policy=required, search_policy=allowed
- 明确说“只根据/严格按照 notebook/不要通用知识/不要联网”：route=rag, notebook_policy=strict, search_policy=forbidden
- 当前处于具体 notebook 下的普通学习问答：notebook_policy=optional，低相关资料不能硬塞进答案
- 最新、当前支持、版本、政策、价格、官网、官方文档、MDN、引用来源、浏览器支持、2025/2026：route=agent, search_policy=required
- 如果用户明确要求联网/搜索但不一定依赖时效：route=agent, search_policy=required

## 注意事项
- 如果用户问的是助手身份、当前模型、当前能力、当前学科/知识库，必须优先归为 meta
- 如果用户只是打招呼或寒暄，优先归为 smalltalk，不要误判成 concept
- 需要最新/联网/搜索/API 的问题 route 必须是 agent
- 明确说“根据资料/当前 notebook/PDF/知识库”的问题 route 必须是 rag
- meta/smalltalk 的 route 通常是 fast
- 如果问题模棱两可，优先判断最可能的类别并降低 confidence
- 如果完全无法判断，归为 concept 并将 confidence 设为 0.5 以下

## 输出格式
请严格以 JSON 格式输出，不包含任何其他内容：
{{"question_type": "concept或problem或practice或review或meta或smalltalk或mcq_problem", "confidence": 0.9, "route": "fast或explain或rag或agent", "route_confidence": 0.9, "notebook_policy": "skip或optional或required或strict", "search_policy": "forbidden或allowed或required", "source_policy": "none或notebook或web或mixed", "reasoning": "判断理由"}}
"""

ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM_PROMPT),
    ("human", "{question}"),
])


# ============================================================
# LLM 实例
# ============================================================

def _get_llm(model_name: str | None = None) -> ChatOpenAI:
    """获取当前激活聊天模型实例。"""
    return get_chat_llm(
        default_model=DEFAULT_CHAT_MODEL,
        temperature=0,
        model_override=model_name,
        timeout_seconds=12.0,
        max_retries=0,
    )


def _invoke_router_chain(
    question: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
    last_question_type_hint: str = "（暂无上一轮问题类型记录）",
    learning_context_hint: str = "（暂无前置学习策略）",
) -> RouterOutput:
    """使用 LangChain structured output 返回 RouterOutput。"""
    llm = _get_llm(model_name)
    return invoke_with_schema(
        ROUTER_PROMPT,
        llm,
        RouterOutput,
        {
            "question": question,
            "short_term_context": short_term_context,
            "session_memory_context": session_memory_context,
            "long_term_context": long_term_context,
            "last_question_type_hint": last_question_type_hint,
            "learning_context_hint": learning_context_hint,
        },
        model_name=model_name,
    )


# ============================================================
# 置信度回退
# ============================================================

CONFIDENCE_THRESHOLD = 0.7


META_PATTERNS = [
    r"^(你是谁|你是什么|你是干什么的|你是什么模型|你现在是什么模型|当前是什么模型)$",
    r"(你|当前|现在|这个助手|该助手).*(什么模型|哪个模型|用的什么模型|当前模型|模型是)",
    r"(你|这个助手|该助手).*(是谁|身份|角色|能做什么|会什么|可以做什么|有什么功能)",
    r"(当前|现在).*(知识库|学科).*(是什么|是哪|哪个|叫什么|状态|信息)",
    r"(当前|现在|这个|该).*(助手|agent)",
    r"(刚才|刚刚|目前|当前|现在).*(讲到哪|聊到哪|重点是什么|在学什么)",
    r"^(我们刚才讲到哪了|这个会话现在的重点是什么|我们现在在学什么)$",
]

SMALLTALK_PATTERNS = [
    r"^(你好|您好|嗨|hi|hello|hey)$",
    r"^(在吗|有人吗|还在吗)$",
    r"^(早上好|中午好|下午好|晚上好)$",
    r"^(哈喽|hello there|嗨嗨)$",
]

REVIEW_PATTERNS = [
    r"(复习|回顾|总结一下|总结下|梳理一下|薄弱点|错题|我哪里错了|帮我整理)",
]

PRACTICE_PATTERNS = [
    r"(给我出|帮我出|来[点些]|再来|出几道|出两道|出一道|练习题|题目|我要练习|我要刷题|给我几题)",
]

PROBLEM_PATTERNS = [
    r"(这道题|这题|求解|求证|证明|计算|怎么做|求.+值|解方程|编程题|算法题)",
]

CONCEPT_PATTERNS = [
    r"^(什么是|什么叫|解释一下|解释下|介绍一下|介绍下|怎么理解|为什么)",
    r"(是什么|有什么区别|区别是什么|原理是什么|作用是什么)",
    r"(讲|解释|展开|介绍).*(概念|知识点)",
    r"(知识库|资料|notebook|笔记本).*(做什么|作用|用途)",
    # 对比理解类
    r"(.+)和(.+)(的区别|有什么不同|哪个更|怎么选|如何区分)",
    r"(对比|比较|区分|区别).*(和|与|vs)",
    r"(.+)vs(.+)",
]

MCQ_PATTERNS = [
    r"(?is)(?:^|\n).{0,200}(?:^|\n)\s*a[\.．、:：\)]\s*.+(?:\n|\r\n?)\s*b[\.．、:：\)]\s*.+(?:\n|\r\n?)\s*c[\.．、:：\)]\s*.+(?:\n|\r\n?)\s*d[\.．、:：\)]\s*.+",
    r"(选择题|单选题).*(选什么|选哪项|哪一个对|判断答案)",
]

EXPLICIT_WEB_ROUTE_PATTERNS = [
    r"(联网|上网|网络搜索|网页搜索|搜索一下|帮我搜|帮我查|查一下|查查|搜索|检索网页)",
    r"(官网|官方网站|官方文档|MDN|Can I use|caniuse|标准文档|引用|来源|出处)",
    r"(外部工具|调用工具|API|接口|系统状态|新闻|天气|赛程|行情)",
]

FRESHNESS_ROUTE_PATTERNS = [
    r"(最新|实时|今天|近期|2025|2026)",
    r"(现在|目前|当前).*(支持|版本|价格|政策|状态|兼容|浏览器)",
    r"(版本|版本发布|政策|价格|浏览器支持|兼容情况|支持情况|现在支持|当前支持)",
]

AGENT_ROUTE_PATTERNS = [
    *EXPLICIT_WEB_ROUTE_PATTERNS,
    *FRESHNESS_ROUTE_PATTERNS,
]

RAG_ROUTE_PATTERNS = [
    r"(当前|这个|该).*(notebook|笔记本|知识库|资料库|资料|文档|pdf|上传内容)",
    r"(根据|依据|基于|参考).*(notebook|笔记本|知识库|资料|文档|pdf|上传内容)",
    r"(在|从).*(notebook|笔记本|知识库|资料|文档|pdf).*(里|中)",
    r"(这份|这个|上述|上面的).*(资料|文档|pdf|笔记)",
    r"(按照|按).*(我的)?(笔记|课程|课件|老师|课堂|讲义)",
    r"(老师|课程|课件|课堂|讲义).*(怎么讲|如何讲|是怎么讲|里怎么说|里面怎么说)",
    r"(总结|概括|梳理).*(我的)?(notebook|笔记|资料|课件|讲义)",
]

STRICT_NOTEBOOK_PATTERNS = [
    r"(只|仅|严格|完全).*(根据|依据|基于|按照|按).*(notebook|笔记本|笔记|知识库|资料|文档|pdf|课件|讲义)",
    r"(根据|依据|基于|按照|按).*(notebook|笔记本|笔记|知识库|资料|文档|pdf|课件|讲义).*(不要|别|不需要).*(通用|外部|联网|搜索)",
    r"(不要|别|不需要).*(通用知识|联网|搜索|外部资料)",
]

FAST_ROUTE_PATTERNS = [
    r"(一句话|直接回答|只要答案|简短回答|不用展开|快速回答)",
    r"^\s*\d+\s*[\+\-\*/]\s*\d+\s*[=？?]?\s*$",
]

# 追问模式：用户在延续上一轮对话，没有切换主题
FOLLOWUP_PATTERNS = [
    r"^(继续|那|然后|那么|那后来|接着|再说|再讲|然后呢|那为什么|那怎么|那如何)$",
    r"^(再深入一点|展开讲|说详细一点|能详细说吗|能展开吗)$",
    r"^(那这个|那这|那这样|那这种|这个为什么|这里为什么)",
    r"^(我还不太懂|还是不明白|没明白|不太理解|能再解释一下吗)",
    r"^(那上面说的|刚才说的|你刚说的|你之前说的)",
    r"^(能|可以)?(给我|帮我)?(讲|解释|展开|说)(一下|下)?.*(这个)?概念(不|吗|嘛)?[？?]?$",
]


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_recent_topic_for_routing(state: AgentState) -> str:
    session_memory = state.get("session_memory") or {}
    if isinstance(session_memory, dict):
        active_topic = str(session_memory.get("active_topic", "") or "").strip()
        if active_topic:
            return active_topic

    for message in reversed(list(state.get("short_term_messages") or [])):
        if not isinstance(message, dict):
            continue
        explanation = message.get("explanation") if isinstance(message.get("explanation"), dict) else {}
        topic = str(explanation.get("topic", "") or "").strip()
        if topic:
            return topic

    memory = state.get("memory") or {}
    if isinstance(memory, dict):
        recent_topics = list(memory.get("recent_topics") or [])
        if recent_topics:
            return str(recent_topics[0]).strip()
    return ""


def _is_followup_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", (question or "")).strip().lower()
    if not normalized:
        return False
    if len(normalized) <= 10:
        return True
    return _matches_any(FOLLOWUP_PATTERNS, normalized)


def _build_contextual_question_for_routing(question: str, state: AgentState) -> str:
    normalized = re.sub(r"\s+", " ", (question or "")).strip()
    if not normalized or not _is_followup_question(normalized):
        return normalized
    anchor = _extract_recent_topic_for_routing(state)
    if not anchor or anchor.lower() in normalized.lower():
        return normalized
    return f"{anchor} {normalized}"


def _is_explicit_notebook_question(question: str) -> bool:
    return _matches_any(RAG_ROUTE_PATTERNS, question.strip().lower())


def _is_strict_notebook_question(question: str) -> bool:
    return _matches_any(STRICT_NOTEBOOK_PATTERNS, question.strip().lower())


def _is_required_search_question(question: str) -> bool:
    normalized = question.strip().lower()
    return _matches_any(EXPLICIT_WEB_ROUTE_PATTERNS, normalized) or _matches_any(
        FRESHNESS_ROUTE_PATTERNS,
        normalized,
    )


def _derive_policies(
    *,
    question: str,
    question_type: QuestionType,
    route: RouteType,
    subject_id: str | None = None,
    suggested_search_policy: SearchPolicy | None = None,
) -> tuple[NotebookPolicy, SearchPolicy, SourcePolicy]:
    explicit_notebook = _is_explicit_notebook_question(question)
    strict_notebook = _is_strict_notebook_question(question)
    required_search = _is_required_search_question(question)
    if question_type in {QuestionType.META, QuestionType.SMALLTALK} or route == RouteType.FAST:
        return NotebookPolicy.SKIP, SearchPolicy.FORBIDDEN, SourcePolicy.NONE

    if strict_notebook:
        return NotebookPolicy.STRICT, SearchPolicy.FORBIDDEN, SourcePolicy.NOTEBOOK

    if explicit_notebook and not required_search:
        return NotebookPolicy.REQUIRED, SearchPolicy.ALLOWED, SourcePolicy.MIXED

    if required_search:
        notebook_policy = NotebookPolicy.OPTIONAL if explicit_notebook else NotebookPolicy.SKIP
        source_policy = SourcePolicy.MIXED if explicit_notebook else SourcePolicy.WEB
        return notebook_policy, SearchPolicy.REQUIRED, source_policy

    if question_type == QuestionType.CONCEPT and not explicit_notebook:
        return NotebookPolicy.SKIP, SearchPolicy.ALLOWED, SourcePolicy.NONE

    if route == RouteType.RAG:
        return NotebookPolicy.OPTIONAL, SearchPolicy.ALLOWED, SourcePolicy.NONE

    if route == RouteType.AGENT:
        return (
            NotebookPolicy.SKIP,
            suggested_search_policy or SearchPolicy.ALLOWED,
            SourcePolicy.WEB if suggested_search_policy == SearchPolicy.REQUIRED else SourcePolicy.NONE,
        )

    return NotebookPolicy.SKIP, SearchPolicy.ALLOWED, SourcePolicy.NONE


def _runtime_policy_fields(
    *,
    notebook_policy: NotebookPolicy,
    search_policy: SearchPolicy,
) -> dict[str, Any]:
    notebook_required = notebook_policy == NotebookPolicy.STRICT
    external_search_required = search_policy == SearchPolicy.REQUIRED
    if notebook_policy == NotebookPolicy.STRICT:
        answer_mode = "notebook_grounded"
        source_usage = "notebook"
    elif notebook_policy in {NotebookPolicy.REQUIRED, NotebookPolicy.OPTIONAL} or external_search_required:
        answer_mode = "hybrid"
        source_usage = "mixed" if external_search_required else "model"
    else:
        answer_mode = "general_teaching"
        source_usage = "model"
    return {
        "notebook_required": notebook_required,
        "external_search_required": external_search_required,
        "answer_mode": answer_mode,
        "source_usage": source_usage,
    }


def _derive_route(
    *,
    question: str,
    question_type: QuestionType,
    subject_id: str | None = None,
    suggested_route: RouteType | None = None,
) -> tuple[RouteType, float, str]:
    normalized = question.strip().lower()
    if question_type in {QuestionType.META, QuestionType.SMALLTALK}:
        return RouteType.FAST, 0.98, "元问题或寒暄适合轻量直接回答。"
    explicit_notebook = _is_explicit_notebook_question(normalized)
    strict_notebook = _is_strict_notebook_question(normalized)
    required_search = _is_required_search_question(normalized)
    if strict_notebook:
        return RouteType.RAG, 0.96, "问题明确要求严格依据 notebook、资料或文档回答。"
    if explicit_notebook and not required_search:
        return RouteType.RAG, 0.9, "问题希望参考当前 notebook、资料或文档，但资料不足时仍可由模型补充说明。"
    if required_search:
        return RouteType.AGENT, 0.95, "问题明确需要外部搜索、工具、来源或最新信息。"
    if suggested_route == RouteType.AGENT:
        return RouteType.AGENT, 0.88, "LLM 路由建议使用外部工具路径。"
    if suggested_route == RouteType.RAG:
        return RouteType.RAG, 0.85, "LLM 路由建议优先使用资料库路径。"
    if question_type == QuestionType.CONCEPT:
        return RouteType.EXPLAIN, 0.9, "普通稳定概念问题优先直接教学讲解，notebook 仅在用户明确要求时作为依据。"
    if _matches_any(FAST_ROUTE_PATTERNS, normalized):
        return RouteType.FAST, 0.78, "用户要求简短或直接回答。"
    if suggested_route == RouteType.FAST:
        return RouteType.FAST, 0.75, "LLM 路由建议轻量回答。"
    return RouteType.EXPLAIN, 0.86, "普通学习问题，适合教学讲解路径。"


def _build_router_output(
    *,
    question: str,
    question_type: QuestionType,
    confidence: float,
    reasoning: str,
    subject_id: str | None = None,
    suggested_route: RouteType | None = None,
) -> RouterOutput:
    route, route_confidence, route_reason = _derive_route(
        question=question,
        question_type=question_type,
        subject_id=subject_id,
        suggested_route=suggested_route,
    )
    notebook_policy, search_policy, source_policy = _derive_policies(
        question=question,
        question_type=question_type,
        route=route,
        subject_id=subject_id,
        suggested_search_policy=SearchPolicy.REQUIRED
        if suggested_route == RouteType.AGENT and _is_required_search_question(question)
        else None,
    )
    return RouterOutput(
        question_type=question_type,
        confidence=confidence,
        route=route,
        route_confidence=route_confidence,
        notebook_policy=notebook_policy,
        search_policy=search_policy,
        source_policy=source_policy,
        reasoning=f"{reasoning} 路线判断：{route_reason}",
    )


def _classify_by_rules(
    question: str,
    last_question_type: str | None = None,
    subject_id: str | None = None,
) -> RouterOutput | None:
    normalized = question.strip().lower()

    for pattern in META_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.META,
                confidence=0.98,
                reasoning="命中了助手身份/模型/能力/知识库相关关键词，属于元问题。",
                subject_id=subject_id,
            )

    for pattern in SMALLTALK_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.SMALLTALK,
                confidence=0.99,
                reasoning="命中了寒暄/打招呼表达，属于闲聊开场，不应进入知识检索。",
                subject_id=subject_id,
            )

    # 追问模式：继承上一轮 question_type（仅限知识类，不继承 smalltalk/meta）
    _inheritable = {"concept", "problem", "review", "mcq_problem"}
    if last_question_type and last_question_type in _inheritable:
        for pattern in FOLLOWUP_PATTERNS:
            if re.search(pattern, normalized):
                try:
                    inherited_type = QuestionType(last_question_type)
                except ValueError:
                    inherited_type = QuestionType.CONCEPT
                return _build_router_output(
                    question=question,
                    question_type=inherited_type,
                    confidence=0.88,
                    reasoning=f"命中了追问模式，继承上一轮 question_type='{last_question_type}'。",
                    subject_id=subject_id,
                )

    for pattern in REVIEW_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.REVIEW,
                confidence=0.93,
                reasoning="命中了复习、错题或薄弱点相关表达。",
                subject_id=subject_id,
            )

    for pattern in PRACTICE_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.PRACTICE,
                confidence=0.95,
                reasoning="命中了明确的出题/练习请求。",
                subject_id=subject_id,
            )

    for pattern in MCQ_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.MCQ_PROBLEM,
                confidence=0.97,
                reasoning="命中了带 A/B/C/D 选项的选择题结构或明确的选择题判题请求。",
                subject_id=subject_id,
            )

    for pattern in PROBLEM_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.PROBLEM,
                confidence=0.83,
                reasoning="命中了求解、证明、计算等解题信号。",
                subject_id=subject_id,
            )

    for pattern in CONCEPT_PATTERNS:
        if re.search(pattern, normalized):
            return _build_router_output(
                question=question,
                question_type=QuestionType.CONCEPT,
                confidence=0.9,
                reasoning="命中了概念解释、原理理解或对比分析类表达。",
                subject_id=subject_id,
            )

    if _matches_any(AGENT_ROUTE_PATTERNS, normalized) or _matches_any(RAG_ROUTE_PATTERNS, normalized):
        return _build_router_output(
            question=question,
            question_type=QuestionType.CONCEPT,
            confidence=0.74,
            reasoning="未命中明确问题类型，但命中了执行路线关键词，按概念问答处理。",
            subject_id=subject_id,
        )

    return None


def _apply_confidence_fallback(result: RouterOutput) -> str:
    """
    如果置信度低于阈值，回退为 concept。

    Args:
        result: LLM 返回的结构化分类结果

    Returns:
        最终的 question_type 字符串
    """
    if result.confidence < CONFIDENCE_THRESHOLD:
        logger.warning(
            f"⚠️ 置信度 {result.confidence:.2f} < {CONFIDENCE_THRESHOLD}，"
            f"原始分类 '{result.question_type.value}' 回退为 'concept'"
        )
        return "concept"
    return result.question_type.value


# ============================================================
# Agent 节点函数
# ============================================================

def router_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：路由 Agent

    流程：
      1. 从 state 取出 question 和 last_question_type（用于追问继承）
      2. 规则分类（含追问模式和对比类）
      3. 规则未命中则调用 LLM 结构化分类
      4. confidence < 0.7 → 回退为 concept
      5. 返回 { "question_type": ... }
    """
    question = state["question"]
    model_name = str(state.get("model_name", "") or "").strip() or None
    subject_id = str(state.get("subject_id", "") or "").strip() or None
    short_term_context = state.get("short_term_context", "（当前会话暂无历史上下文）")
    session_memory_context = state.get("session_memory_context", "（当前会话暂无中期摘要）")
    long_term_context = state.get("long_term_context", "（暂无长期学习记忆）")
    learning_context = state.get("learning_context") if isinstance(state.get("learning_context"), dict) else {}

    # 从 session_memory 或 memory 中取上一轮问题类型，用于追问继承
    session_memory = state.get("session_memory") or {}
    memory = state.get("memory") or {}
    last_question_type = (
        str(session_memory.get("last_question_type", "") or "")
        or str(memory.get("last_question_type", "") or "")
    ).strip() or None
    contextual_question = _build_contextual_question_for_routing(str(question), state)
    routing_question = contextual_question or str(question)

    logger.info(
        f"🔀 路由 Agent 收到问题: {question[:80]}… "
        f"| routing_question={routing_question[:80]}… "
        f"| last_type={last_question_type or 'none'}"
    )

    rule_result = _classify_by_rules(
        routing_question,
        last_question_type=last_question_type,
        subject_id=subject_id,
    )
    if rule_result:
        logger.info(
            f"🔀 规则分类命中: type={rule_result.question_type.value}, "
            f"route={rule_result.route.value}, confidence={rule_result.confidence:.2f}, "
            f"reason={rule_result.reasoning}"
        )
        runtime_fields = _runtime_policy_fields(
            notebook_policy=rule_result.notebook_policy,
            search_policy=rule_result.search_policy,
        )
        return {
            "question_type": rule_result.question_type.value,
            "route": rule_result.route.value,
            "route_confidence": rule_result.route_confidence,
            "notebook_policy": rule_result.notebook_policy.value,
            "search_policy": rule_result.search_policy.value,
            "source_policy": rule_result.source_policy.value,
            **runtime_fields,
            "contextual_question": routing_question,
            "route_reason": rule_result.reasoning,
        }

    # LLM 分类时注入上一轮类型作为上下文提示
    last_type_hint = (
        f"上一轮问题类型是 '{last_question_type}'，如果当前问题是追问或延续，请优先沿用该类型。"
        if last_question_type
        else "（暂无上一轮问题类型记录）"
    )
    learning_context_hint = (
        "mode={mode}, level={level}, need_steps={need_steps}, need_examples={need_examples}".format(
            mode=learning_context.get("mode", ""),
            level=learning_context.get("level", ""),
            need_steps=learning_context.get("need_steps", False),
            need_examples=learning_context.get("need_examples", False),
        )
        if learning_context
        else "（暂无前置学习策略）"
    )

    try:
        result = _invoke_router_chain(
            question=routing_question,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
            last_question_type_hint=last_type_hint,
            learning_context_hint=learning_context_hint,
        )
        logger.info(
            f"🔀 LLM 分类结果: type={result.question_type.value}, route={result.route.value}, "
            f"confidence={result.confidence:.2f}, "
            f"reason={result.reasoning}"
        )

        question_type_value = _apply_confidence_fallback(result)
        try:
            question_type = QuestionType(question_type_value)
        except ValueError:
            question_type = QuestionType.CONCEPT
        route, route_confidence, route_reason = _derive_route(
            question=routing_question,
            question_type=question_type,
            subject_id=subject_id,
            suggested_route=result.route,
        )
        notebook_policy, search_policy, source_policy = _derive_policies(
            question=routing_question,
            question_type=question_type,
            route=route,
            subject_id=subject_id,
            suggested_search_policy=result.search_policy,
        )
        route_reason = f"{result.reasoning} 路线判断：{route_reason}"

    except Exception as e:
        logger.error(f"❌ 路由 Agent 调用失败: {e}")
        logger.info("🔀 兜底：默认分类为 concept")
        question_type_value = "concept"
        route, route_confidence, route_reason = _derive_route(
            question=routing_question,
            question_type=QuestionType.CONCEPT,
            subject_id=subject_id,
        )
        notebook_policy, search_policy, source_policy = _derive_policies(
            question=routing_question,
            question_type=QuestionType.CONCEPT,
            route=route,
            subject_id=subject_id,
        )

    logger.info(f"🔀 最终路由结果: type={question_type_value}, route={route.value}")
    runtime_fields = _runtime_policy_fields(
        notebook_policy=notebook_policy,
        search_policy=search_policy,
    )
    return {
        "question_type": question_type_value,
        "route": route.value,
        "route_confidence": route_confidence,
        "notebook_policy": notebook_policy.value,
        "search_policy": search_policy.value,
        "source_policy": source_policy.value,
        **runtime_fields,
        "contextual_question": routing_question,
        "route_reason": route_reason,
    }
