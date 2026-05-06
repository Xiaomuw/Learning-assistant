from __future__ import annotations

from typing import Any

from app.application.chat.messages import build_message_process

NODE_EVENT_MAP: dict[str, dict[str, Any]] = {
    "preflight_node": {
        "event": "status",
        "fields": ["normalized_question", "graph_warnings"],
    },
    "learning_context_node": {
        "event": "status",
        "fields": ["learning_context"],
    },
    "router": {
        "event": "routing",
        "fields": [
            "question_type",
            "route",
            "route_confidence",
            "route_reason",
            "contextual_question",
            "notebook_policy",
            "search_policy",
            "source_policy",
            "learning_context",
        ],
    },
    "guard_node": {
        "event": "status",
        "fields": [
            "route",
            "notebook_policy",
            "search_policy",
            "source_policy",
            "guard",
            "allow_tools",
            "allow_search",
        ],
    },
    "teaching_state_node": {
        "event": "status",
        "fields": [
            "teaching_input_type",
            "teaching_user_state",
            "teaching_knowledge_point",
            "pending_check",
            "stuck_count",
        ],
    },
    "rag_node": {
        "event": "status",
        "fields": [
            "raw_retrieved_docs",
            "retrieved_docs",
            "contextual_query",
            "retrieval_diagnosis",
            "retrieval_relevance",
            "rag_ready",
            "rag_warning",
            "web_search_required",
            "notebook_policy",
            "search_policy",
            "source_policy",
        ],
    },
    "context_audit_node": {
        "event": "status",
        "fields": [
            "raw_retrieved_docs",
            "verified_context",
            "context_audit",
            "retrieved_docs",
            "retrieval_diagnosis",
            "retrieval_relevance",
            "rag_ready",
            "notebook_policy",
            "source_policy",
        ],
    },
    "web_search_node": {
        "event": "status",
        "fields": [
            "retrieved_docs",
            "contextual_query",
            "retrieval_diagnosis",
            "external_tool_calls",
            "web_search_attempted",
            "web_search_used",
            "web_search_error",
            "web_search_diagnosis",
        ],
    },
    "qa_agent_node": {
        "event": "explanation",
        "fields": [
            "question_type",
            "route",
            "teaching_input_type",
            "explanation",
            "final_answer",
            "execution_mode",
            "tool_calls",
            "tool_decision_rounds",
            "reasoning_summary",
            "source_usage",
            "external_tool_calls",
            "web_search_attempted",
            "web_search_used",
            "web_search_error",
            "degraded",
            "selected_model_profile",
            "primary_model_id",
            "fallback_model_id",
            "fallback_used",
            "fallback_reason",
            "model_attempts",
            "streaming_mode",
            "model_latency_ms",
        ],
    },
    "answer_delta": {
        "event": "answer_delta",
        "fields": ["delta", "streaming_mode", "is_synthetic_delta"],
    },
    "qa_answer_guard_node": {
        "event": "explanation",
        "fields": [
            "question_type",
            "route",
            "teaching_input_type",
            "explanation",
            "final_answer",
            "degraded",
            "answer_guard_applied",
            "answer_guard_reason",
            "external_tool_calls",
            "web_search_attempted",
            "web_search_used",
            "web_search_error",
        ],
    },
    "teaching_response_node": {
        "event": "explanation",
        "fields": [
            "question_type",
            "route",
            "teaching_input_type",
            "explanation",
            "final_answer",
            "teaching_user_state",
            "teaching_phase",
            "last_teaching_action",
            "pending_check",
            "code_execution_result",
        ],
    },
    "quiz_mastery_node": {
        "event": "status",
        "fields": ["quiz_focus_points", "quiz_target_difficulty", "quiz_plan"],
    },
    "quiz_knowledge_node": {
        "event": "status",
        "fields": ["quiz_focus_points"],
    },
    "quiz_rag_node": {
        "event": "status",
        "fields": ["quiz_rag_docs", "quiz_rag_diagnosis", "graph_warnings"],
    },
    "quiz_context_node": {
        "event": "status",
        "fields": ["quiz_context"],
    },
    "quiz_generate_node": {
        "event": "status",
        "fields": ["quiz_items", "quiz_generation_status"],
    },
    "quiz_quality_node": {
        "event": "status",
        "fields": ["quiz_quality_report", "quiz_generation_status"],
    },
    "quiz_retry_node": {
        "event": "status",
        "fields": ["quiz_retry_count", "graph_warnings"],
    },
    "quiz_output_node": {
        "event": "quiz",
        "fields": [
            "question_type",
            "route",
            "quiz_items",
            "quiz_generation_status",
            "final_answer",
            "quiz_request",
            "quiz_clarification",
        ],
    },
    "memory_node": {
        "event": "memory",
        "fields": ["memory"],
    },
    "meta_node": {
        "event": "explanation",
        "fields": ["question_type", "route", "explanation", "final_answer"],
    },
    "mcq_solver": {
        "event": "explanation",
        "fields": ["question_type", "route", "explanation", "final_answer"],
    },
    "graph_error_node": {
        "event": "explanation",
        "fields": ["question_type", "route", "graph_error", "explanation", "final_answer", "degraded"],
    },
    "finalize_node": {
        "event": "status",
        "fields": [
            "finalized",
            "final_response_type",
            "route_decision",
            "graph_warnings",
            "degraded",
        ],
    },
}


def extract_event_data(node: str, state_update: dict[str, Any]) -> dict[str, Any]:
    mapping = NODE_EVENT_MAP.get(node, {})
    fields = mapping.get("fields", [])

    data: dict[str, Any] = {}
    for field in fields:
        if field not in state_update:
            continue
        value = state_update[field]
        if field == "raw_retrieved_docs" and isinstance(value, list):
            data["raw_doc_count"] = len(value)
            data["raw_top_scores"] = [round(d.get("score", 0), 2) for d in value[:3]]
        elif field == "verified_context" and isinstance(value, list):
            data["verified_count"] = len(value)
            data["verified_top_scores"] = [round(d.get("score", 0), 2) for d in value[:3]]
        elif field == "retrieved_docs" and isinstance(value, list):
            data["doc_count"] = len(value)
            data["top_scores"] = [round(d.get("score", 0), 2) for d in value[:3]]
        elif field == "quiz_rag_docs" and isinstance(value, list):
            data["doc_count"] = len(value)
            data["top_scores"] = [round(d.get("score", 0), 2) for d in value[:3]]
        else:
            data[field] = value
    return data


def event_name_for_node(node: str) -> str:
    mapping = NODE_EVENT_MAP.get(node, {})
    return str(mapping.get("event", node))


__all__ = ["build_message_process", "event_name_for_node", "extract_event_data"]
