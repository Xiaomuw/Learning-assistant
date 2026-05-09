"""
Q&A Tracing Helpers
===================
组装主问答链路的 LangSmith metadata / tags / inputs / outputs。
"""

from __future__ import annotations

from typing import Any

from app.domains.qa.capability_tools import (
    NOTEBOOK_RETRIEVE,
    WEB_EXTRACT,
    WEB_SEARCH,
)
from app.domains.qa.schemas import AgentExecutionResult, AgentRequest
from app.shared.schemas.model_profile import ModelProfile


def _normalize_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "")
    legacy_map = {
        "search_notebook_context": (NOTEBOOK_RETRIEVE, "notebook"),
        "tavily_web_search": (WEB_SEARCH, "tavily"),
        "mcp_web_search": (WEB_SEARCH, "mcp"),
        "mcp_web_read": (WEB_EXTRACT, "mcp"),
    }
    capability, provider = legacy_map.get(
        name,
        (
            str(item.get("capability") or name),
            str(item.get("provider") or "internal"),
        ),
    )
    return {
        "capability": str(item.get("capability") or capability),
        "provider": str(item.get("provider") or provider),
        "success": bool(item.get("success")),
        "doc_count": int(item.get("doc_count") or 0),
        "is_external": bool(item.get("is_external") or capability in {WEB_SEARCH, WEB_EXTRACT}),
    }


def _tool_stats(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [_normalize_tool_call(item) for item in tool_calls if isinstance(item, dict)]
    web_calls = [
        item
        for item in normalized
        if item["capability"] in {WEB_SEARCH, WEB_EXTRACT}
    ]
    notebook_used = any(
        item["capability"] == NOTEBOOK_RETRIEVE
        and bool(item["success"])
        and int(item.get("doc_count") or 0) > 0
        for item in normalized
    )
    web_used = any(
        item["capability"] in {WEB_SEARCH, WEB_EXTRACT}
        and bool(item["success"])
        and int(item.get("doc_count") or 0) > 0
        for item in normalized
    )
    return {
        "used_web_search": web_used,
        "web_tool_providers": sorted(set(item["provider"] for item in web_calls if item["provider"])),
        "used_notebook": notebook_used,
        "external_tool_count": len(web_calls),
        "tool_degraded": any(not item["success"] for item in normalized),
    }


def _raw_retrieved_count(result: AgentExecutionResult) -> int:
    diagnosis = result.retrieval_diagnosis or {}
    for key in ("raw_count", "raw_doc_count", "raw_hit_count", "candidate_count"):
        value = diagnosis.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return len(result.retrieved_docs)


def _doc_preview(doc: dict[str, Any]) -> dict[str, Any]:
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    content = str(doc.get("content") or doc.get("document") or doc.get("text") or "")
    return {
        "id": str(doc.get("id") or metadata.get("id") or "")[:120],
        "source_type": str(doc.get("source_type") or metadata.get("source_type") or metadata.get("retrieval_source") or ""),
        "source_name": str(metadata.get("source_name") or metadata.get("title") or doc.get("source_name") or ""),
        "score": doc.get("score") if doc.get("score") is not None else metadata.get("score"),
        "content_preview": content[:500],
    }


def build_qa_trace_tags(
    *,
    request_mode: str,
    question_type: str,
    model_profile: ModelProfile,
) -> list[str]:
    return [
        "qa",
        f"entry:{request_mode}",
        f"question_type:{question_type}",
        f"model_family:{model_profile.family.lower()}",
    ]


def build_qa_trace_metadata(
    *,
    request: AgentRequest,
    model_profile: ModelProfile,
) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "subject_id": request.subject_id,
        "question_type": request.question_type,
        "selected_model": model_profile.model_id,
        "model_provider": model_profile.provider,
        "model_family": model_profile.family,
        "supports_tool_calling": model_profile.supports_tool_calling,
        "supports_structured_output": model_profile.supports_structured_output,
        "context_window": model_profile.context_window,
        "supported_modalities": list(model_profile.supported_modalities),
        "thinking_mode": bool(request.runtime_context.get("thinking_mode", False)),
        "reasoning_visibility": "safe_summary_only",
        "raw_reasoning_content_logged": False,
    }


def build_qa_trace_inputs(
    *,
    request: AgentRequest,
    request_mode: str,
) -> dict[str, Any]:
    return {
        "request_mode": request_mode,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "subject_id": request.subject_id,
        "subject_name": request.subject_name,
        "question_type": request.question_type,
        "question": request.question,
        "thinking_mode": bool(request.runtime_context.get("thinking_mode", False)),
        "route": str(request.runtime_context.get("route") or ""),
        "source_policy": str(request.runtime_context.get("source_policy") or ""),
        "notebook_policy": str(request.runtime_context.get("notebook_policy") or ""),
        "search_policy": str(request.runtime_context.get("search_policy") or ""),
    }


def build_qa_trace_outputs(result: AgentExecutionResult) -> dict[str, Any]:
    payload = {
        "execution_mode": result.execution_mode,
        "degraded": result.degraded,
        "tool_calls_count": len(result.tool_calls),
        "tool_decision_rounds_count": len(result.tool_decision_rounds),
        "source_usage": result.source_usage,
        "contextual_query": result.contextual_query,
        "retrieved_docs_count": len(result.retrieved_docs),
        "verified_context_count": len(result.retrieved_docs),
        "raw_retrieved_count": _raw_retrieved_count(result),
        "retrieval_diagnosis": result.retrieval_diagnosis.get("diagnosis", ""),
        "safe_reasoning_summary": result.reasoning_summary,
        "reasoning_visibility": "safe_summary_only",
        "final_answer": result.final_answer,
        "final_answer_empty": not bool(str(result.final_answer or "").strip()),
        "final_answer_length": len(str(result.final_answer or "")),
        "tool_decision_rounds": result.tool_decision_rounds,
        "retrieved_doc_previews": [_doc_preview(item) for item in result.retrieved_docs[:5] if isinstance(item, dict)],
        "primary_model_id": result.primary_model_id,
        "fallback_model_id": result.fallback_model_id,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "streaming_mode": result.streaming_mode,
        "streaming_token_count": result.streaming_token_count,
        "streaming_degraded_reason": result.streaming_degraded_reason,
    }
    payload.update(_tool_stats(result.tool_calls))
    return payload


def build_qa_result_metadata(result: AgentExecutionResult) -> dict[str, Any]:
    payload = {
        "execution_mode": result.execution_mode,
        "degraded": result.degraded,
        "tool_calls_count": len(result.tool_calls),
        "tool_decision_rounds_count": len(result.tool_decision_rounds),
        "source_usage": result.source_usage,
        "retrieval_diagnosis": result.retrieval_diagnosis.get("diagnosis", ""),
        "safe_reasoning_summary": result.reasoning_summary,
        "reasoning_visibility": "safe_summary_only",
        "final_answer_length": len(str(result.final_answer or "")),
        "primary_model_id": result.primary_model_id,
        "fallback_model_id": result.fallback_model_id,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "streaming_mode": result.streaming_mode,
        "streaming_token_count": result.streaming_token_count,
        "streaming_degraded_reason": result.streaming_degraded_reason,
    }
    payload.update(_tool_stats(result.tool_calls))
    return payload
