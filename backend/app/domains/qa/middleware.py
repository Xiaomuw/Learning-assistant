"""
Q&A Middleware
==============
主问答链路的统一前后置处理。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Callable

from app.domains.qa.schemas import AgentExecutionResult, AgentRequest, AnswerSchema
from app.shared.schemas.model_profile import ModelProfile

MAX_CONTEXT_BUDGET_RATIO = 0.45

# 直接回复类型（不套 AnswerSchema 结构，final_answer 即全部）
_PLAIN_ANSWER_TYPES = {"smalltalk", "meta"}

# 诊断信息关键词——如果 mistakes 包含这些内容，属于内部技术信息，不应展示给用户
_DIAGNOSTIC_KEYWORDS = [
    "检索",
    "命中率",
    "脉络识别",
    "笔记本专属",
    "RAG",
    "rag",
    "retrieval",
    "泛化解释",
    "知识库覆盖",
    "无法匹配",
    "doc_count",
    "rag_ready",
    "高质量匹配",
    "score",
    "diagnosis",
]


def _sanitize_mistakes(mistakes: str | None, question_type: str = "") -> str:
    """
    过滤 mistakes 字段中的内部诊断信息。
    如果 mistakes 包含 RAG / 检索相关的技术内容，就不展示给用户。
    """
    if not mistakes:
        return ""
    text = mistakes.strip()
    if any(keyword in text for keyword in _DIAGNOSTIC_KEYWORDS):
        return ""
    # 额外检查：如果是直接将 prompt 指令原文输出（常见于「【】」括号开头）
    if text.startswith("【") or text.startswith("-") and "笔记本" in text:
        return ""
    return text


def _normalize_text(value: str, *, max_length: int | None = None) -> str:
    normalized = re.sub(r"\s+", " ", (value or "")).strip()
    if max_length and len(normalized) > max_length:
        return normalized[: max_length - 1] + "…"
    return normalized


def _estimate_tokens(*parts: str) -> int:
    return sum(max(1, len((part or "").strip()) // 4) for part in parts if part)


def _heuristic_summarize(value: str, max_chars: int) -> str:
    normalized = _normalize_text(value)
    if len(normalized) <= max_chars:
        return normalized
    head = normalized[: max_chars // 2].rstrip()
    tail = normalized[-max(80, max_chars // 4) :].lstrip()
    return f"{head} … {tail}"


def preprocess_middleware(
    agent_request: AgentRequest,
    model_profile: ModelProfile,
) -> AgentRequest:
    normalized_question = _normalize_text(agent_request.question)
    if not normalized_question:
        raise ValueError("问题不能为空")

    unsupported_modalities = [
        modality
        for modality in agent_request.input_modalities
        if modality not in model_profile.supported_modalities
    ]
    if unsupported_modalities:
        raise ValueError(
            "当前模型不支持这些输入类型："
            + ", ".join(unsupported_modalities)
        )

    normalized_request = replace(
        agent_request,
        question=normalized_question,
        short_term_context=_normalize_text(agent_request.short_term_context),
        session_memory_context=_normalize_text(agent_request.session_memory_context),
        long_term_context=_normalize_text(agent_request.long_term_context),
        subject_description=_normalize_text(agent_request.subject_description, max_length=600),
    )

    estimated_tokens = _estimate_tokens(
        normalized_request.question,
        normalized_request.short_term_context,
        normalized_request.session_memory_context,
        normalized_request.long_term_context,
        normalized_request.subject_description,
    )
    max_budget = max(4_000, int(model_profile.context_window * MAX_CONTEXT_BUDGET_RATIO))

    if estimated_tokens <= max_budget:
        return normalized_request

    return replace(
        normalized_request,
        question=_heuristic_summarize(normalized_request.question, 2_800),
        short_term_context=_heuristic_summarize(normalized_request.short_term_context, 1_200),
        session_memory_context=_heuristic_summarize(
            normalized_request.session_memory_context, 800
        ),
        long_term_context=_heuristic_summarize(normalized_request.long_term_context, 800),
    )


def _coerce_answer_schema(raw_output: Any) -> AnswerSchema | None:
    if raw_output is None:
        return None
    if isinstance(raw_output, AnswerSchema):
        return raw_output
    if isinstance(raw_output, dict):
        return AnswerSchema.model_validate(raw_output)
    if isinstance(raw_output, str):
        return AnswerSchema.model_validate_json(raw_output)
    return None


def _wrap_plain_text_as_answer(raw_output: Any, question_type: str = "") -> AnswerSchema:
    """将纯文本包装为 AnswerSchema，按问题类型定制默认值"""
    text = _normalize_text(str(raw_output or "抱歉，这一轮没有拿到可用回答。"), max_length=1200)

    if question_type == "smalltalk":
        return AnswerSchema(
            topic="日常问候",
            thinking=text,
            steps=[text],
            mistakes="",
            similar=["开始今天的学习吧", "告诉我你想学什么"],
            final_answer=text,
        )
    if question_type == "meta":
        return AnswerSchema(
            topic="助手信息",
            thinking=text,
            steps=[text],
            mistakes="",
            similar=["查看当前笔记本", "了解我的学习进度"],
            final_answer=text,
        )
    if question_type == "problem":
        return AnswerSchema(
            topic="解题引导",
            thinking=text,
            steps=[text],
            mistakes="尝试自己先想一步，再对照提示",
            similar=["继续追问解题思路", "让我换一种方式引导"],
            final_answer=text,
        )
    if question_type == "review":
        return AnswerSchema(
            topic="复习巩固",
            thinking=text,
            steps=[text],
            mistakes="请重点关注你的薄弱知识点",
            similar=["查看我的薄弱点分析", "继续刷相关练习题"],
            final_answer=text,
        )
    # concept / practice / 其他：通用默认值
    return AnswerSchema(
        topic="当前问题",
        thinking=text,
        steps=[text],
        mistakes="",
        similar=["继续追问这个主题", "让我结合你的笔记本继续解释"],
        final_answer=text,
    )


def _final_answer_from_validated_answer(answer: AnswerSchema) -> str:
    if answer.final_answer:
        return answer.final_answer
    step_answer = "\n\n".join(str(item).strip() for item in answer.steps[:3] if str(item).strip())
    if step_answer:
        return step_answer
    return "这轮暂时没有生成完整答案，请换一种问法再试。"


def postprocess_middleware(
    agent_result: AgentExecutionResult,
    model_profile: ModelProfile,
    *,
    question_type: str = "",
    repair: Callable[[Any], AnswerSchema | None] | None = None,
    fallback: Callable[[], AgentExecutionResult] | None = None,
) -> AgentExecutionResult:
    # smalltalk / meta 走 direct_answer 模式：raw_output 即为自然语言，直接作为 final_answer
    if (
        question_type in _PLAIN_ANSWER_TYPES
        and agent_result.execution_mode == "direct_answer"
        and isinstance(agent_result.raw_output, str)
        and agent_result.raw_output.strip()
    ):
        plain_text = agent_result.raw_output.strip()
        agent_result.answer = _wrap_plain_text_as_answer(plain_text, question_type)
        agent_result.final_answer = plain_text
        return agent_result

    try:
        validated = agent_result.answer or _coerce_answer_schema(agent_result.raw_output)
    except Exception:
        validated = None

    if validated is None and repair is not None:
        try:
            validated = repair(agent_result.raw_output)
        except Exception:
            validated = None

    if (
        validated is None
        and agent_result.execution_mode == "direct_answer"
        and isinstance(agent_result.raw_output, str)
        and agent_result.raw_output.strip()
    ):
        validated = _wrap_plain_text_as_answer(agent_result.raw_output, question_type)
        agent_result.degraded = True

    if validated is None and fallback is not None:
        fallback_result = fallback()
        fallback_result.degraded = True
        fallback_result.execution_mode = agent_result.execution_mode
        fallback_result.tool_calls = list(agent_result.tool_calls)
        fallback_result.selected_model_profile = dict(agent_result.selected_model_profile)
        fallback_result.primary_model_id = agent_result.primary_model_id
        fallback_result.fallback_model_id = agent_result.fallback_model_id
        fallback_result.fallback_used = agent_result.fallback_used
        fallback_result.fallback_reason = agent_result.fallback_reason
        fallback_result.model_attempts = list(agent_result.model_attempts)
        return fallback_result

    if validated is None:
        validated = _wrap_plain_text_as_answer(agent_result.raw_output, question_type)
        agent_result.degraded = True

    # 过滤内部诊断信息，确保 mistakes 只展示学习者易错点
    if validated.mistakes:
        validated = validated.model_copy(
            update={"mistakes": _sanitize_mistakes(validated.mistakes, question_type)}
        )

    agent_result.answer = validated
    agent_result.final_answer = _final_answer_from_validated_answer(validated)
    return agent_result
