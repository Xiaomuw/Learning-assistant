"""
Q&A Agent Node
==============
主问答链路统一 runtime 节点。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.infrastructure.llm.langsmith import qa_tracing_context, trace_run
from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_model_profile
from app.domains.qa.runtime import create_agent
from app.domains.qa.schemas import AgentRequest
from app.domains.qa.tracing import (
    build_qa_trace_inputs,
    build_qa_trace_metadata,
    build_qa_trace_outputs,
    build_qa_result_metadata,
    build_qa_trace_tags,
)
from app.shared.schemas.state import AgentState


def qa_agent(state: AgentState) -> dict[str, Any]:
    active_model = str(state.get("model_name", "") or DEFAULT_CHAT_MODEL)
    model_profile = get_model_profile(active_model)

    effective_question = str(state.get("contextual_question") or state.get("question", "") or "")

    request = AgentRequest(
        user_id=state.get("user_id", ""),
        session_id=state.get("session_id", ""),
        subject_id=state.get("subject_id", "general"),
        subject_name=state.get("subject_name", "通用知识"),
        subject_description=state.get("subject_description", ""),
        question=effective_question,
        question_type=state.get("question_type", "concept"),
        memory=state.get("memory", {}),
        user_style_name=state.get("user_style_name", ""),
        user_style_prompt=state.get("user_style_prompt", ""),
        short_term_messages=state.get("short_term_messages", []) or [],
        short_term_context=state.get("short_term_context", ""),
        session_memory=state.get("session_memory", {}) or {},
        session_memory_context=state.get("session_memory_context", ""),
        long_term_context=state.get("long_term_context", ""),
        model_name=active_model,
        runtime_context={
            "rag_precomputed": bool(state.get("rag_precomputed", False)),
            "raw_retrieved_docs": list(state.get("raw_retrieved_docs", []) or []),
            "verified_context": list(state.get("verified_context", []) or state.get("retrieved_docs", []) or []),
            "notebook_retrieved": bool(state.get("notebook_retrieved", False)),
            "notebook_context": str(state.get("notebook_context", "") or ""),
            "context_audit": dict(state.get("context_audit") or {}),
            "retrieved_docs": list(state.get("retrieved_docs", []) or []),
            "contextual_query": state.get("contextual_query", ""),
            "contextual_question": state.get("contextual_question", ""),
            "is_rewritten": bool(state.get("is_rewritten", False)),
            "retrieval_diagnosis": dict(state.get("retrieval_diagnosis") or {}),
            "retrieval_relevance": dict(state.get("retrieval_relevance") or {}),
            "rag_ready": bool(state.get("rag_ready", False)),
            "rag_warning": state.get("rag_warning", ""),
            "route": state.get("route", ""),
            "notebook_policy": state.get("notebook_policy", "skip"),
            "notebook_required": bool(state.get("notebook_required", False)),
            "search_policy": state.get("search_policy", "forbidden"),
            "external_search_required": bool(state.get("external_search_required", False)),
            "source_policy": state.get("source_policy", "none"),
            "answer_mode": state.get("answer_mode", "general_teaching"),
            "source_usage": state.get("source_usage", "model"),
            "tool_decision_rounds": list(state.get("tool_decision_rounds", []) or []),
            "reasoning_summary": str(state.get("reasoning_summary", "") or ""),
            "learning_context": dict(state.get("learning_context") or {}),
            "guard": dict(state.get("guard") or {}),
            "allow_tools": bool(state.get("allow_tools", False)),
            "allow_search": bool(state.get("allow_search", False)),
            "external_tool_calls": list(state.get("external_tool_calls", []) or []),
            "web_search_attempted": bool(state.get("web_search_attempted", False)),
            "web_search_used": bool(state.get("web_search_used", False)),
            "web_search_error": str(state.get("web_search_error", "") or ""),
            "thinking_mode": bool(state.get("thinking_mode", False)),
        },
    )
    request_mode = str(state.get("request_mode", "sync") or "sync").strip().lower()
    trace_name = "chat.sse.qa" if request_mode == "sse" else "chat.sync.qa"

    logger.info(
        f"🤖 qa_agent 运行 | model={active_model} | "
        f"profile={model_profile.family} | "
        f"tool_calling={model_profile.supports_tool_calling}"
    )

    agent = create_agent(request, dict(state), model_profile)
    trace_metadata = build_qa_trace_metadata(
        request=request,
        model_profile=model_profile,
    )
    trace_tags = build_qa_trace_tags(
        request_mode=request_mode,
        question_type=request.question_type,
        model_profile=model_profile,
    )

    with qa_tracing_context(metadata=trace_metadata, tags=trace_tags):
        with trace_run(
            name=trace_name,
            run_type="chain",
            inputs=build_qa_trace_inputs(request=request, request_mode=request_mode),
            metadata=trace_metadata,
            tags=trace_tags,
        ) as root_run:
            result = agent.run()
            root_run.metadata.update(build_qa_result_metadata(result))
            root_run.end(outputs=build_qa_trace_outputs(result))
    explanation = {}
    final_answer = result.final_answer
    if result.answer:
        explanation = result.answer.model_dump(exclude={"final_answer"})
        final_answer = final_answer or result.answer.final_answer or result.answer.thinking

    return {
        "retrieved_docs": result.retrieved_docs,
        "verified_context": result.retrieved_docs,
        "raw_retrieved_docs": list(state.get("raw_retrieved_docs", []) or []),
        "notebook_retrieved": bool(state.get("notebook_retrieved", False)),
        "notebook_context": str(state.get("notebook_context", "") or ""),
        "context_audit": dict(state.get("context_audit") or {}),
        "is_rewritten": result.is_rewritten,
        "contextual_query": result.contextual_query,
        "retrieval_diagnosis": result.retrieval_diagnosis,
        "explanation": explanation,
        "final_answer": final_answer,
        "execution_mode": result.execution_mode,
        "tool_calls": result.tool_calls,
        "tool_decision_rounds": result.tool_decision_rounds,
        "reasoning_summary": result.reasoning_summary,
        "source_usage": result.source_usage,
        "external_tool_calls": list(state.get("external_tool_calls", []) or []),
        "web_search_attempted": bool(state.get("web_search_attempted", False)),
        "web_search_used": bool(state.get("web_search_used", False)),
        "web_search_error": str(state.get("web_search_error", "") or ""),
        "route": state.get("route", ""),
        "notebook_policy": state.get("notebook_policy", "skip"),
        "notebook_required": bool(state.get("notebook_required", False)),
        "search_policy": state.get("search_policy", "forbidden"),
        "external_search_required": bool(state.get("external_search_required", False)),
        "source_policy": state.get("source_policy", "none"),
        "answer_mode": state.get("answer_mode", "general_teaching"),
        "guard": dict(state.get("guard") or {}),
        "degraded": result.degraded,
        "selected_model_profile": result.selected_model_profile,
        "primary_model_id": result.primary_model_id,
        "fallback_model_id": result.fallback_model_id,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "model_attempts": list(result.model_attempts),
    }
