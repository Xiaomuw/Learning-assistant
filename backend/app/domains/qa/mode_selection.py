from __future__ import annotations

from app.domains.qa.schemas import AgentRequest
from app.shared.schemas.model_profile import ModelProfile

# 这些类型直接回复，不需要工具调用或结构化输出
_DIRECT_ANSWER_TYPES = {"smalltalk", "meta", "simple_fact", "practice_generation"}

_RAG_DETERMINISTIC_TYPES = {"concept", "problem", "review", "mcq_problem"}


def _non_tool_answer_mode(model_profile: ModelProfile) -> str:
    if model_profile.supports_structured_output:
        return "structured_output"
    return "deterministic_context"


def select_execution_mode(request: AgentRequest, model_profile: ModelProfile) -> str:
    """
    根据问题类型、RAG 状态和模型能力选择执行模式：

    - direct_answer         : smalltalk / meta — 直接自然语言回复
    - tool_calling          : route/guard 已许可，交给模型决定是否调用可用工具
    - deterministic_context : RAG 已就绪，走确定性主链路（无需工具）
    - structured_output     : 模型支持结构化输出但不需要工具
    """
    # smalltalk / meta：强制走轻量直接回复，不进工具循环
    if request.question_type in _DIRECT_ANSWER_TYPES:
        return "direct_answer"

    route = str(request.runtime_context.get("route", "") or "").strip()
    guard = (
        dict(request.runtime_context.get("guard") or {})
        if isinstance(request.runtime_context.get("guard"), dict)
        else {}
    )
    allow_tools = bool(request.runtime_context.get("allow_tools", False) or guard.get("allow_tools", False))
    allow_search = bool(request.runtime_context.get("allow_search", False) or guard.get("allow_search", False))
    if route == "fast":
        if model_profile.provider == "DeepSeek" and not model_profile.supports_structured_output:
            return "direct_answer"
        return _non_tool_answer_mode(model_profile)

    rag_precomputed = bool(request.runtime_context.get("rag_precomputed", False))
    rag_ready = bool(request.runtime_context.get("rag_ready", False))
    notebook_policy = str(request.runtime_context.get("notebook_policy", "") or "").strip()

    if rag_precomputed and request.question_type in _RAG_DETERMINISTIC_TYPES and (
        rag_ready or notebook_policy == "strict"
    ):
        return "deterministic_context"

    if model_profile.provider == "DeepSeek":
        # DeepSeek 当前端点不走稳定结构化输出；当 notebook 只是可选且没有
        # 预检索证据时，应直接让模型回答，避免落入“暂无资料”的确定性模板。
        return "direct_answer"

    if model_profile.supports_tool_calling and allow_tools:
        # 模型优先：route/guard 只提供工具边界，是否真的调用工具由模型循环决定。
        return "tool_calling"

    # 兼容旧 graph 预检索分支：不支持工具调用时，才消费预检索上下文走确定性链路。
    return _non_tool_answer_mode(model_profile)
