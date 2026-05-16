from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from app.domains.qa.lightweight_intent import classify_lightweight_answer_intent
from app.orchestration.graphs.qa.adapter import DeterministicQARuntimeAdapter, QARuntimeAdapter
from app.orchestration.graphs.qa.fact_boundary import (
    QUESTION_META_TOOL_USAGE,
    QUESTION_REALTIME_OR_FRESH,
    QUESTION_STABLE_KNOWLEDGE,
    classify_question_boundary,
)
from app.orchestration.graphs.qa.state import QAGraphState
from app.orchestration.graphs.shared.schemas import (
    ConceptRef,
    EvidenceChunk,
    FinalResponse,
    GraphError,
    GraphErrorSeverity,
    GraphType,
    LearningEvent,
    LearningEventType,
    SourceLevel,
    SourcePolicy,
    ToolCapability,
    ToolResult,
    ToolStatus,
    build_learning_event,
    learning_event_hash_key,
)
from app.orchestration.graphs.shared.trace import append_trace_record
from app.knowledge.concept_registry import get_concept_registry
from app.services.tooling.executor import ToolExecutor
from app.services.tooling.schemas import ToolExecutionRequest, ToolRiskLevel
from app.shared.schemas.subject import CANONICAL_SUBJECT_IDS, DEFAULT_SUBJECTS


GRAPH_VERSION = "0.1.0"
QA_FLOW_VERSION = "408-flow-v1"
MIN_EVIDENCE_SCORE = 0.55
PARTIAL_EVIDENCE_SCORE = 0.55
STRONG_EVIDENCE_SCORE = 0.70
DEFAULT_EVIDENCE_CONFIDENCE_THRESHOLD = 0.72
DEFAULT_EVIDENCE_CONFIDENCE_HIGH = 0.82
DEFAULT_EVIDENCE_CONFIDENCE_LOW = 0.45
MAX_KNOWLEDGE_ROUTES = 4
MAX_WEB_REPAIRS = 1
MAX_ANSWER_REPAIR_ATTEMPTS = 1
DEFAULT_MAX_WEB_RETRY = 1
DEFAULT_MAX_RETHINK_RETRY = 1
DEFAULT_MAX_GENERATE_RETRY = 1


def _bounded_retry_count(value: Any, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _max_repair_count(state: QAGraphState) -> int:
    raw_max = state.get("max_repair_count")
    if raw_max is None:
        return MAX_ANSWER_REPAIR_ATTEMPTS
    try:
        return max(0, int(raw_max))
    except (TypeError, ValueError):
        return MAX_ANSWER_REPAIR_ATTEMPTS


def _max_web_retry(state: QAGraphState) -> int:
    return _bounded_retry_count(state.get("max_web_retry"), default=DEFAULT_MAX_WEB_RETRY)


def _max_rethink_retry(state: QAGraphState) -> int:
    return _bounded_retry_count(state.get("max_rethink_retry"), default=DEFAULT_MAX_RETHINK_RETRY)


def _max_generate_retry(state: QAGraphState) -> int:
    return _bounded_retry_count(state.get("max_generate_retry"), default=DEFAULT_MAX_GENERATE_RETRY)


def _can_retry_web(state: QAGraphState) -> bool:
    return _bounded_retry_count(state.get("web_retry_count"), default=0) < _max_web_retry(state)


def _can_retry_rethink(state: QAGraphState) -> bool:
    repair_count = _bounded_retry_count(state.get("repair_count") or state.get("answer_repair_attempt_count"), default=0)
    return (
        _bounded_retry_count(state.get("rethink_retry_count"), default=0) < _max_rethink_retry(state)
        and repair_count < _max_repair_count(state)
    )


def _can_retry_generate(state: QAGraphState) -> bool:
    return _bounded_retry_count(state.get("generate_retry_count"), default=0) < _max_generate_retry(state)


def input_normalize_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Normalize the raw user input and initialize the v2 QA chain state."""

    question = _question(state)
    normalized_question = " ".join(question.split()).strip()
    source_policy = _source_policy({**state, "user_message": normalized_question})
    runtime_time_context = _runtime_time_context(state)
    question_boundary = classify_question_boundary(
        normalized_question,
        current_date=runtime_time_context.get("currentDate"),
    ).as_dict()
    web_search_requested = _web_search_requested_for_state(state)
    has_web_search_tool = _tool_executor_has_web_search(tool_executor)
    web_search_enabled = _web_search_enabled_for_state(
        {**state, "source_policy": source_policy, "user_message": normalized_question},
        has_web_search_tool=has_web_search_tool,
    )
    messages = list(state.get("messages") or [{"role": "user", "content": normalized_question}])
    context_dependency = {
        "is_context_dependent": _is_context_dependent_question(normalized_question),
        "signals": _context_dependency_signals(normalized_question),
    }
    question_type = str(state.get("question_type") or _infer_question_type(normalized_question))
    repair_count = int(state.get("repair_count") or state.get("answer_repair_attempt_count") or 0)
    max_repair_count = _max_repair_count(state)
    return {
        "run_id": str(state.get("run_id") or uuid4()),
        "graph_type": GraphType.QA.value,
        "graph_version": str(state.get("graph_version") or GRAPH_VERSION),
        "qa_flow_version": str(state.get("qa_flow_version") or QA_FLOW_VERSION),
        "source_policy": source_policy,
        "user_message": normalized_question,
        "normalized_question": normalized_question,
        "runtime_time_context": runtime_time_context,
        "question_boundary": question_boundary,
        "allow_web": bool(state.get("allow_web", False)),
        "web_search_requested": web_search_requested,
        "has_web_search_tool": has_web_search_tool,
        "web_search_enabled": web_search_enabled,
        "previous_tool_invocation_trace": _previous_assistant_tool_trace(messages),
        "context_dependency": context_dependency,
        "messages": messages,
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "tool_requests": list(state.get("tool_requests") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "repair_count": repair_count,
        "max_repair_count": max_repair_count,
        "answer_repair_attempt_count": repair_count,
        "web_retry_count": _bounded_retry_count(state.get("web_retry_count"), default=0),
        "max_web_retry": _bounded_retry_count(state.get("max_web_retry"), default=DEFAULT_MAX_WEB_RETRY),
        "rethink_retry_count": _bounded_retry_count(state.get("rethink_retry_count"), default=0),
        "max_rethink_retry": _bounded_retry_count(state.get("max_rethink_retry"), default=DEFAULT_MAX_RETHINK_RETRY),
        "generate_retry_count": _bounded_retry_count(state.get("generate_retry_count"), default=0),
        "max_generate_retry": _bounded_retry_count(state.get("max_generate_retry"), default=DEFAULT_MAX_GENERATE_RETRY),
        "web_staging_notes": list(state.get("web_staging_notes") or []),
        "qa_request": {
            "question": normalized_question,
            "question_type": question_type,
            "user_id": str(state.get("user_id") or ""),
            "thread_id": state.get("thread_id"),
            "notebook_id": state.get("notebook_id"),
            "course_id": state.get("course_id"),
            "source_policy": source_policy,
            "web_search_requested": web_search_requested,
        },
    }


def qa_intent_classifier_node(state: QAGraphState) -> dict[str, Any]:
    """Classify QA-local sub-intent without overriding Orchestrator graph routing."""

    question = _normalized_question(state)
    raw_intent = _infer_intent(question)
    intent = _qa_scoped_intent(raw_intent)
    question_type = _question_type_from_intent(intent, question)
    parent_decision = dict(state.get("parent_intent_decision") or {})
    parent_intent = str(parent_decision.get("intent") or "")
    alignment_status = "no_parent_intent"
    if parent_intent:
        alignment_status = "aligned" if parent_intent == "qa" else "parent_routed_to_qa_child"
    if raw_intent != intent:
        alignment_status = "cross_graph_signal_recorded"
    qa_request = {
        **dict(state.get("qa_request") or {}),
        "question": question,
        "question_type": question_type,
    }
    return {
        "intent_result": {
            "intent": intent,
            "raw_intent": raw_intent,
            "confidence": _intent_confidence(intent),
            "reason": _intent_reason(intent),
            "parent_intent": parent_intent,
            "alignment_status": alignment_status,
        },
        "question_type": question_type,
        "qa_request": qa_request,
        "intent_alignment": {
            "parent_intent": parent_intent,
            "raw_internal_intent": raw_intent,
            "qa_scoped_intent": intent,
            "status": alignment_status,
        },
    }


def intent_classifier_node(state: QAGraphState) -> dict[str, Any]:
    """Backward-compatible alias for the QA-local intent classifier."""

    return qa_intent_classifier_node(state)


def normalize_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Diagram-aligned wrapper for input normalization."""

    return input_normalize_node(state, tool_executor=tool_executor)


def goal_router_node(state: QAGraphState) -> dict[str, Any]:
    """Route the QA-local 408 flow goal."""

    classifier_update = qa_intent_classifier_node(state)
    question = _normalized_question({**state, **classifier_update})
    intent = str((classifier_update.get("intent_result") or {}).get("intent") or "")
    context_dependency = dict(state.get("context_dependency") or {})
    active_topic = _active_topic(state)
    goal_route = "answer_408"
    reason = "answer_408_default"
    if not question:
        goal_route = "clarify"
        reason = "empty_question"
    elif context_dependency.get("is_context_dependent") and not active_topic:
        goal_route = "clarify"
        reason = "context_dependent_without_topic"
    elif intent in {"smalltalk", "simple_fact"}:
        goal_route = "out_of_scope"
        reason = f"{intent}_handled_outside_qagraph"
    elif not (_looks_like_408_scope(question) or _looks_like_408_scope(active_topic)):
        goal_route = "out_of_scope"
        reason = "outside_408_scope"

    qa_request = {
        **dict((classifier_update.get("qa_request") or state.get("qa_request") or {})),
        "question": question,
        "goal_route": goal_route,
        "goal_route_reason": reason,
    }
    return {
        **classifier_update,
        "goal_route": goal_route,
        "trace_records": append_trace_record(
            state,
            "goal_router",
            goal_route=goal_route,
            reason=reason,
            qa_flow_version=QA_FLOW_VERSION,
        ),
        "qa_request": qa_request,
    }


def route_after_goal_router(state: QAGraphState) -> str:
    route = str(state.get("goal_route") or "answer_408")
    if route == "clarify":
        return "clarify"
    if route == "out_of_scope":
        return "out_of_scope"
    return "retrieve_core_408"


def clarify_node(state: QAGraphState) -> dict[str, Any]:
    question = _normalized_question(state)
    answer = (
        "我需要再确认一下你的问题。请补充具体的 408 科目、知识点或题目上下文，"
        "例如“数据结构里的二叉树遍历”或“计算机网络里的 TCP 拥塞控制”。"
    )
    if not question:
        answer = "请先输入一个 408 相关问题，我再继续帮你解答。"
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        coach_actions=["ask_clarification"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "clarify",
            "goal_route": "clarify",
            "qa_flow_version": QA_FLOW_VERSION,
        },
    )
    return {
        "trace_records": append_trace_record(state, "clarify", final_response_status="clarify"),
        "final_response": response.model_dump(mode="json"),
        "source_usage": "model",
    }


def out_of_scope_node(state: QAGraphState) -> dict[str, Any]:
    response = FinalResponse(
        answer="这个问题看起来不属于 408 计算机基础范围。我可以继续帮你解答数据结构、计算机网络、组成原理和操作系统相关问题。",
        source_level=SourceLevel.NONE,
        coach_actions=["redirect_to_408_scope"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "out_of_scope",
            "goal_route": "out_of_scope",
            "qa_flow_version": QA_FLOW_VERSION,
        },
    )
    return {
        "trace_records": append_trace_record(state, "out_of_scope", final_response_status="out_of_scope"),
        "final_response": response.model_dump(mode="json"),
        "source_usage": "model",
    }


def context_resolver_node(state: QAGraphState) -> dict[str, Any]:
    """Resolve vague follow-up wording into a full question when context exists."""

    normalized_question = _normalized_question(state)
    context_dependency = dict(state.get("context_dependency") or {})
    resolved_question = normalized_question
    resolved_topic = ""
    if context_dependency.get("is_context_dependent"):
        resolved_topic = _active_topic(state)
        if resolved_topic:
            resolved_question = f"{resolved_topic}：{normalized_question}"

    qa_request = {
        **dict(state.get("qa_request") or {}),
        "question": resolved_question,
        "context_dependency": context_dependency,
    }
    return {
        "resolved_question": resolved_question,
        "context_dependency": {
            **context_dependency,
            "resolved_topic": resolved_topic,
            "resolved_question": resolved_question,
        },
        "qa_request": qa_request,
    }


def concept_linker_node(state: QAGraphState) -> dict[str, Any]:
    """Bind the resolved question to the taxonomy registry before retrieval."""

    question = _resolved_question(state)
    subject_hint = str(state.get("notebook_id") or state.get("course_id") or "").strip() or None
    match = get_concept_registry().match_query(question, subject_id=subject_hint)
    concept_linking = match.model_dump(mode="json")
    update: dict[str, Any] = {
        "concept_linking": concept_linking,
        "qa_request": {
            **dict(state.get("qa_request") or {}),
            "question": question,
            "concept_linking": concept_linking,
            "subject_id": match.subject_id or subject_hint,
            "concept_id": match.concept_id,
            "topic_id": match.topic_id,
        },
    }
    if match.status == "matched" and match.concept_id:
        existing_concepts = list(state.get("concepts") or [])
        update["concepts"] = [
            *existing_concepts,
            ConceptRef(
                concept_id=match.concept_id,
                name=match.concept_name or match.concept_id,
                confidence=match.confidence,
                source="concept_registry",
            ).model_dump(mode="json"),
        ]
    return update


def knowledge_router_node(state: QAGraphState) -> dict[str, Any]:
    """Select one or more knowledge bases before retrieval."""

    question = _resolved_question(state)
    source_policy = _source_policy(state)
    routes: list[dict[str, Any]] = []
    candidate_routes: list[dict[str, Any]] = []

    notebook_id = state.get("notebook_id")
    course_id = state.get("course_id")
    concept_linking = dict(state.get("concept_linking") or {})
    linked_subject_id = str(concept_linking.get("subject_id") or "").strip()
    concept_metadata = {
        "concept_id": concept_linking.get("concept_id") or "",
        "concept_name": concept_linking.get("concept_name") or "",
        "topic_id": concept_linking.get("topic_id") or "",
        "confidence": concept_linking.get("confidence") or 0.0,
        "status": concept_linking.get("status") or "",
    }
    if _should_consider_knowledge_candidates(question, source_policy):
        for candidate in _available_knowledge_bases(state):
            route = _route_from_candidate(candidate, question)
            if route is not None:
                candidate_routes.append(_route_with_metadata(route, concept_metadata))

    has_named_route = any(
        str(route.get("source_reason") or "") == "explicit_named_knowledge_base"
        for route in candidate_routes
    )
    should_use_current_route = _should_use_current_knowledge_base(state, question, source_policy) and not has_named_route

    if notebook_id and should_use_current_route:
        routes.append(
            _knowledge_route(
                knowledge_base_id=str(notebook_id),
                subject_id=str(notebook_id),
                source_reason="current_notebook",
                priority=20,
                metadata=concept_metadata,
            )
        )
    elif should_use_current_route:
        routes.append(
            _knowledge_route(
                knowledge_base_id="current_notebook",
                subject_id=None,
                source_reason="explicit_notebook_request",
                priority=30,
                metadata=concept_metadata,
            )
        )

    if (
        course_id
        and str(course_id) != str(notebook_id or "")
        and should_use_current_route
    ):
        routes.append(
            _knowledge_route(
                knowledge_base_id=str(course_id),
                subject_id=str(course_id),
                source_reason="current_course",
                priority=40,
                metadata=concept_metadata,
            )
        )
    if (
        linked_subject_id
        and concept_linking.get("status") in {"matched", "subject_only", "ambiguous"}
        and not should_use_current_route
        and not has_named_route
    ):
        routes.append(
            _knowledge_route(
                knowledge_base_id=linked_subject_id,
                subject_id=linked_subject_id,
                source_reason="concept_registry",
                priority=12,
                metadata=concept_metadata,
            )
        )

    routes.extend(candidate_routes)

    deduped = _dedupe_routes(routes)
    retrieval_skipped_reason = ""
    if not deduped:
        retrieval_skipped_reason = _retrieval_skipped_reason(state, question, source_policy)
    return {
        "knowledge_routes": deduped[:MAX_KNOWLEDGE_ROUTES],
        "retrieval_skipped_reason": retrieval_skipped_reason,
        "qa_request": {
            **dict(state.get("qa_request") or {}),
            "question": question,
            "knowledge_route_count": len(deduped[:MAX_KNOWLEDGE_ROUTES]),
        },
    }


def internal_retrieval_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Retrieve only internal/notebook evidence for selected knowledge bases."""

    _emit_status(
        stream_stage="internal_retrieval",
        stage_label="知识库检索",
        detail="正在检索内部知识库和课程资料。",
    )
    routes = list(state.get("knowledge_routes") or [])
    question = _resolved_question(state)
    source_policy = _source_policy(state)
    existing_usable = [
        item
        for item in _collect_evidence(state)
        if item.source_type in {"notebook", "course"} and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    if existing_usable:
        return {
            "trace_records": append_trace_record(
                state,
                "internal_retrieval",
                rag_called=False,
                rag_planned=False,
                requested_count=0,
                result_count=0,
                reason="preloaded_evidence_available",
            ),
            "retrieval_report": {
                "stage": "internal_retrieval",
                "route_count": len(routes),
                "requested_count": 0,
                "result_count": 0,
                "reason": "preloaded_evidence_available",
                "web_requested_count": 0,
            },
            "web_search_attempted": False,
            "web_search_reason": "not_requested_before_evidence_judge",
        }

    existing_requests = list(state.get("tool_requests") or [])
    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    request_routes: list[tuple[ToolExecutionRequest, dict[str, Any] | None, str]] = []
    for route in routes:
        request_routes.append(
            (
                _tool_request(
                    state,
                    capability=ToolCapability.NOTEBOOK_RETRIEVE,
                    question=question,
                    route=route,
                    risk_level=ToolRiskLevel.LOW,
                    source_policy=source_policy,
                ),
                route,
                "notebook",
            )
        )
    requests = [item[0] for item in request_routes]
    request_payloads = [item.model_dump(mode="json") for item in requests]

    if not requests:
        return {
            "trace_records": append_trace_record(
                state,
                "internal_retrieval",
                rag_called=False,
                rag_planned=False,
                requested_count=0,
                result_count=0,
                reason=str(state.get("retrieval_skipped_reason") or "no_retrieval_request"),
            ),
            "retrieval_report": {
                "stage": "internal_retrieval",
                "route_count": len(routes),
                "requested_count": 0,
                "result_count": 0,
                "reason": str(state.get("retrieval_skipped_reason") or "no_retrieval_request"),
                "web_requested_count": 0,
            },
            "web_search_attempted": False,
            "web_search_reason": "not_requested_before_evidence_judge",
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    if tool_executor is None:
        return {
            "trace_records": append_trace_record(
                state,
                "internal_retrieval",
                rag_called=False,
                rag_planned=True,
                requested_count=len(requests),
                result_count=len(existing_results),
                reason="planned_without_executor",
            ),
            "tool_requests": [*existing_requests, *request_payloads],
            "retrieval_report": {
                "stage": "internal_retrieval",
                "route_count": len(routes),
                "requested_count": len(requests),
                "result_count": len(existing_results),
                "reason": "planned_without_executor",
                "web_requested_count": 0,
            },
            "web_search_attempted": False,
            "web_search_reason": "not_requested_before_evidence_judge",
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    new_results: list[ToolResult] = []
    new_errors: list[dict[str, Any]] = []
    for request, route, retrieval_source in request_routes:
        try:
            result = tool_executor.execute(request)
        except Exception as exc:  # noqa: BLE001 - retrieval failure must not abort the QA graph
            result = _tool_error_result(request, exc)
            new_errors.append(
                GraphError(
                    code="qa_retrieval_tool_failed",
                    message=exc.__class__.__name__,
                    node="internal_retrieval",
                    severity=GraphErrorSeverity.WARNING,
                    metadata={"capability": request.capability.value},
                ).model_dump(mode="json")
            )
        new_results.append(_tag_tool_result_evidence(result, route=route, retrieval_source=retrieval_source))

    merged_results = [*existing_results, *[item.model_dump(mode="json") for item in new_results]]
    return {
        "trace_records": append_trace_record(
            state,
            "internal_retrieval",
            rag_called=True,
            rag_planned=True,
            requested_count=len(requests),
            result_count=len(new_results),
            success_count=len([item for item in new_results if item.status.value == "success"]),
            error_count=len(new_errors),
        ),
        "tool_requests": [*existing_requests, *request_payloads],
        "tool_results": merged_results,
        "errors": [*list(state.get("errors") or []), *new_errors],
        "retrieval_report": {
            "stage": "internal_retrieval",
            "route_count": len(routes),
            "requested_count": len(requests),
            "result_count": len(new_results),
            "success_count": len([item for item in new_results if item.status.value == "success"]),
            "error_count": len(new_errors),
            "web_requested_count": 0,
        },
        "web_search_attempted": False,
        "web_search_reason": "not_requested_before_evidence_judge",
        "web_search_iteration": int(state.get("web_search_iteration") or 0),
    }


def retrieval_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for the internal retrieval stage."""

    return internal_retrieval_node(state, tool_executor=tool_executor)


def retrieve_core_408_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Resolve context, route to canonical 408 knowledge bases, and retrieve core evidence."""

    working: dict[str, Any] = dict(state)
    updates: dict[str, Any] = {}
    for node in (context_resolver_node, concept_linker_node, knowledge_router_node):
        node_update = node(working)  # type: ignore[arg-type]
        working.update(node_update)
        updates.update(node_update)

    routes = _core_408_routes(working)
    working["knowledge_routes"] = routes
    updates["knowledge_routes"] = routes
    retrieval_update = internal_retrieval_node(working, tool_executor=tool_executor)  # type: ignore[arg-type]
    updates.update(retrieval_update)
    updates["retrieval_report"] = {
        **dict(retrieval_update.get("retrieval_report") or {}),
        "stage": "retrieve_core_408",
        "core_408_subject_ids": list(CANONICAL_SUBJECT_IDS),
        "route_count": len(routes),
    }
    updates["trace_records"] = append_trace_record(
        {**working, **retrieval_update},
        "retrieve_core_408",
        route_count=len(routes),
        subject_ids=[route.get("subject_id") for route in routes],
        result_count=len(_collect_evidence({**working, **retrieval_update})),
    )
    return updates


def web_search_if_needed_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Run web search only after internal evidence is judged insufficient."""

    source_policy = _source_policy(state)
    gate = dict(state.get("evidence_gate") or {})
    question = _resolved_question(state)
    web_search_requested = _web_search_requested_for_state(state)
    reason = str(gate.get("reason") or "evidence_judge_not_sufficient")
    if web_search_requested:
        reason = "client_requested_web_search"
    elif _has_external_search_signal(question):
        reason = "explicit_external_search_signal"
    existing_requests = list(state.get("tool_requests") or [])
    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    retrieval_report = dict(state.get("retrieval_report") or {})
    allowed = _should_run_web_retrieval(state, question, source_policy)
    should_run_web = bool(allowed)

    if not should_run_web:
        blocked_reason = "internal_evidence_sufficient" if gate.get("sufficient") else "source_policy_disallows_web"
        if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
            blocked_reason = "source_policy_notebook_only"
        elif not (web_search_requested or _has_external_search_signal(question)):
            blocked_reason = "no_external_search_signal"
        _emit_status(
            stream_stage="web_search_if_needed",
            stage_label="联网补充",
            detail="内部证据已足够或当前策略不允许联网，本轮不触发 web_search。",
            status="skipped",
        )
        return {
            "trace_records": append_trace_record(
                state,
                "web_search_if_needed",
                web_called=False,
                web_planned=False,
                reason=blocked_reason,
                web_result_count=0,
            ),
            "retrieval_report": {
                **retrieval_report,
                "web_requested_count": 0,
                "web_result_count": 0,
                "web_search_stage": "skipped",
                "web_search_reason": blocked_reason,
            },
            "web_search_attempted": False,
            "web_search_reason": blocked_reason,
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    _emit_status(
        stream_stage="web_search_if_needed",
        stage_label="联网补充",
        detail="内部证据不足，正在按 source_policy 补充联网信息。",
    )
    request = _tool_request(
        state,
        capability=ToolCapability.WEB_SEARCH,
        question=question,
        route=None,
        risk_level=ToolRiskLevel.MEDIUM,
        source_policy=source_policy,
    )
    request_payload = request.model_dump(mode="json")
    if tool_executor is None:
        return {
            "trace_records": append_trace_record(
                state,
                "web_search_if_needed",
                web_called=False,
                web_planned=True,
                reason="planned_without_executor",
                web_requested_count=1,
                web_result_count=0,
            ),
            "tool_requests": [*existing_requests, request_payload],
            "pending_web_evidence": [],
            "web_evidence": [],
            "retrieval_report": {
                **retrieval_report,
                "web_requested_count": 1,
                "web_result_count": 0,
                "web_search_stage": "planned_without_executor",
                "web_search_reason": reason,
            },
            "web_search_attempted": False,
            "web_search_reason": "planned_without_executor",
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    new_errors: list[dict[str, Any]] = []
    try:
        result = tool_executor.execute(request)
    except Exception as exc:  # noqa: BLE001 - web fallback must fail open
        result = _tool_error_result(request, exc)
        new_errors.append(
            GraphError(
                code="qa_retrieval_tool_failed",
                message=exc.__class__.__name__,
                node="web_search_if_needed",
                severity=GraphErrorSeverity.WARNING,
                metadata={"capability": request.capability.value},
            ).model_dump(mode="json")
        )

    tagged = _tag_tool_result_evidence(result, route=None, retrieval_source="web")
    candidate_web_evidence = [
        item
        for item in tagged.evidence
        if item.text.strip()
    ]
    return {
        "trace_records": append_trace_record(
            state,
            "web_search_if_needed",
            web_called=True,
            web_planned=True,
            reason=reason,
            web_requested_count=1,
            web_result_count=len(candidate_web_evidence),
            web_success_count=1 if tagged.status == ToolStatus.SUCCESS else 0,
            web_error_count=len(new_errors),
        ),
        "tool_requests": [*existing_requests, request_payload],
        "tool_results": [*existing_results, tagged.model_dump(mode="json")],
        "pending_web_evidence": [item.model_dump(mode="json") for item in candidate_web_evidence],
        "web_evidence": [],
        "errors": [*list(state.get("errors") or []), *new_errors],
        "retrieval_report": {
            **retrieval_report,
            "web_requested_count": 1,
            "web_result_count": len(candidate_web_evidence),
            "web_success_count": 1 if tagged.status == ToolStatus.SUCCESS else 0,
            "web_error_count": len(new_errors),
            "web_search_stage": "executed",
            "web_search_reason": reason,
        },
        "web_search_attempted": True,
        "web_search_reason": reason,
        "web_search_iteration": int(state.get("web_search_iteration") or 0) + 1,
    }


def web_query_rewrite_node(state: QAGraphState) -> dict[str, Any]:
    """Build a compact 408-focused web query for the enrichment branch."""

    retry_count = _bounded_retry_count(state.get("web_retry_count"), default=0) + 1
    question = _resolved_question(state)
    concept = dict(state.get("concept_linking") or {})
    subject_name = str(concept.get("subject_name") or "").strip()
    concept_name = str(concept.get("concept_name") or "").strip()
    query_parts = [question, concept_name, subject_name, "408 计算机考研"]
    query = " ".join(part for part in query_parts if part).strip()
    reason = _web_search_reason_for_state(state, question=question)
    return {
        "web_query": query,
        "web_retry_count": retry_count,
        "web_search_reason": reason,
        "trace_records": append_trace_record(
            state,
            "web_query_rewrite",
            web_retry_count=retry_count,
            max_web_retry=_max_web_retry(state),
            reason=reason,
            query_preview=query[:120],
        ),
    }


def web_search_node_408(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Run the generic web_search capability with the rewritten 408 query."""

    source_policy = _source_policy(state)
    query = str(state.get("web_query") or _resolved_question(state)).strip()
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value or not _web_search_enabled_for_state(state, has_web_search_tool=True):
        return {
            "web_search_attempted": False,
            "web_search_reason": "source_policy_disallows_web",
            "pending_web_evidence": [],
            "trace_records": append_trace_record(state, "web_search", web_called=False, reason="source_policy_disallows_web"),
        }

    request = _tool_request(
        {**state, "resolved_question": query},
        capability=ToolCapability.WEB_SEARCH,
        question=query,
        route=None,
        risk_level=ToolRiskLevel.MEDIUM,
        source_policy=source_policy,
    )
    existing_requests = list(state.get("tool_requests") or [])
    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    request_payload = request.model_dump(mode="json")
    if tool_executor is None:
        return {
            "tool_requests": [*existing_requests, request_payload],
            "pending_web_evidence": [],
            "web_search_attempted": False,
            "web_search_reason": "planned_without_executor",
            "trace_records": append_trace_record(
                state,
                "web_search",
                web_called=False,
                web_planned=True,
                reason="planned_without_executor",
                web_retry_count=int(state.get("web_retry_count") or 0),
            ),
        }

    new_errors: list[dict[str, Any]] = []
    try:
        result = tool_executor.execute(request)
    except Exception as exc:  # noqa: BLE001
        result = _tool_error_result(request, exc)
        new_errors.append(
            GraphError(
                code="qa_web_search_failed",
                message=exc.__class__.__name__,
                node="web_search",
                severity=GraphErrorSeverity.WARNING,
                metadata={"capability": request.capability.value},
            ).model_dump(mode="json")
        )
    tagged = _tag_tool_result_evidence(result, route=None, retrieval_source="web")
    pending = [item for item in tagged.evidence if item.text.strip()]
    return {
        "tool_requests": [*existing_requests, request_payload],
        "tool_results": [*existing_results, tagged.model_dump(mode="json")],
        "pending_web_evidence": [item.model_dump(mode="json") for item in pending],
        "errors": [*list(state.get("errors") or []), *new_errors],
        "web_search_attempted": True,
        "web_search_reason": _web_search_reason_for_state(state, question=query),
        "web_search_iteration": int(state.get("web_search_iteration") or 0) + 1,
        "retrieval_report": {
            **dict(state.get("retrieval_report") or {}),
            "web_requested_count": 1,
            "web_result_count": len(pending),
            "web_search_stage": "executed",
            "web_query": query,
        },
        "trace_records": append_trace_record(
            {**state, "tool_results": [*existing_results, tagged.model_dump(mode="json")]},
            "web_search",
            web_called=True,
            web_planned=True,
            web_result_count=len(pending),
            web_success_count=1 if tagged.status == ToolStatus.SUCCESS else 0,
            web_error_count=len(new_errors),
            web_retry_count=int(state.get("web_retry_count") or 0),
        ),
    }


def web_source_filter_node(state: QAGraphState) -> dict[str, Any]:
    candidates = _parse_evidence_list(state.get("pending_web_evidence") or [])
    filtered = [
        item
        for item in candidates
        if item.text.strip()
        and item.score >= 0.2
        and not _is_low_quality_web_source(item)
    ]
    return {
        "web_filtered_sources": [item.model_dump(mode="json") for item in filtered],
        "trace_records": append_trace_record(
            state,
            "web_source_filter",
            candidate_count=len(candidates),
            filtered_count=len(filtered),
        ),
    }


def web_extract_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    filtered = _parse_evidence_list(state.get("web_filtered_sources") or [])
    _ = tool_executor
    # No default web_extract adapter is registered yet; keep search snippets as extracted text.
    return {
        "web_extracted_evidence": [item.model_dump(mode="json") for item in filtered],
        "pending_web_evidence": [item.model_dump(mode="json") for item in filtered],
        "retrieval_report": {
            **dict(state.get("retrieval_report") or {}),
            "web_extract_skipped_reason": "web_extract_adapter_unavailable",
            "web_extracted_count": len(filtered),
        },
        "trace_records": append_trace_record(
            state,
            "web_extract",
            extracted_count=len(filtered),
            extract_skipped_reason="web_extract_adapter_unavailable",
        ),
    }


def web_knowledge_grade_node(state: QAGraphState) -> dict[str, Any]:
    update = external_evidence_judge_node({**state, "pending_web_evidence": list(state.get("web_extracted_evidence") or [])})
    update["trace_records"] = append_trace_record(
        {**state, **update},
        "web_knowledge_grade",
        web_knowledge_usable=bool((update.get("external_evidence_gate") or {}).get("sufficient")),
        usable_evidence_count=len(update.get("web_evidence") or []),
    )
    return update


def route_after_web_knowledge_grade(state: QAGraphState) -> str:
    gate = dict(state.get("external_evidence_gate") or {})
    if gate.get("sufficient"):
        return "web_to_408_note"
    if _can_retry_web(state):
        return "web_query_rewrite"
    return "hard_fallback"


def web_to_408_note_node(state: QAGraphState) -> dict[str, Any]:
    web_evidence = _parse_evidence_list(state.get("web_evidence") or [])
    notes = []
    for index, evidence in enumerate(web_evidence, start=1):
        notes.append(
            evidence.model_copy(
                update={
                    "id": evidence.id or f"web-staging-{index}",
                    "metadata": {
                        **dict(evidence.metadata),
                        "staging_scope": "state",
                        "knowledge_card_type": "web_to_408_note",
                        "qa_flow_version": QA_FLOW_VERSION,
                    },
                }
            )
        )
    return {
        "web_staging_notes": [item.model_dump(mode="json") for item in notes],
        "trace_records": append_trace_record(
            state,
            "web_to_408_note",
            note_count=len(notes),
            persisted=False,
        ),
    }


def upsert_web_staging_node(state: QAGraphState) -> dict[str, Any]:
    notes = _parse_evidence_list(state.get("web_staging_notes") or [])
    return {
        "web_staging_notes": [item.model_dump(mode="json") for item in notes],
        "trace_records": append_trace_record(
            state,
            "upsert_web_staging",
            note_count=len(notes),
            persisted=False,
            storage="state",
        ),
    }


def retrieve_augmented_node(state: QAGraphState) -> dict[str, Any]:
    notes = _parse_evidence_list(state.get("web_staging_notes") or [])
    internal = _parse_evidence_list(state.get("notebook_evidence") or state.get("evidence") or [])
    merged = _dedupe_evidence([*internal, *notes])
    return {
        "evidence": [item.model_dump(mode="json") for item in merged],
        "web_evidence": [item.model_dump(mode="json") for item in notes],
        "source_usage": _source_usage_from_evidence(merged),
        "retrieval_report": {
            **dict(state.get("retrieval_report") or {}),
            "stage": "retrieve_augmented",
            "web_staging_note_count": len(notes),
            "augmented_evidence_count": len(merged),
        },
        "trace_records": append_trace_record(
            state,
            "retrieve_augmented",
            web_staging_note_count=len(notes),
            augmented_evidence_count=len(merged),
        ),
    }


def internal_evidence_judge_node(state: QAGraphState) -> dict[str, Any]:
    """Named wrapper for the internal evidence gate described by the QA subgraph."""

    return evidence_judge_node(state)


def grade_context_node(state: QAGraphState) -> dict[str, Any]:
    """Diagram-aligned context sufficiency gate for core and augmented evidence."""

    staged = _parse_evidence_list(state.get("web_staging_notes") or [])
    if not staged:
        update = internal_evidence_judge_node(state)
        update["trace_records"] = append_trace_record(
            {**state, **update},
            "grade_context",
            context_sufficient=bool((update.get("evidence_gate") or {}).get("sufficient")),
            internal_evidence_confidence=dict(update.get("evidence_confidence") or {}),
            source="core_408",
        )
        return update

    internal = _parse_evidence_list(state.get("notebook_evidence") or state.get("evidence") or [])
    merged = _dedupe_evidence([*internal, *staged])
    confidence = _evidence_confidence(
        state,
        question=_resolved_question(state),
        evidence=merged,
        source_policy=SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
    )
    sufficient = bool(confidence.get("sufficient") or staged)
    gate = {
        "sufficient": sufficient,
        "insufficient": not sufficient,
        "source_policy": _source_policy(state),
        "usable_evidence_refs": [item.id for item in merged],
        "usable_evidence_count": len(merged),
        "missing_topic": _resolved_question(state),
        "reason": "augmented_408_context" if sufficient else "augmented_context_insufficient",
        "status": "augmented" if sufficient else "insufficient",
        "evidence_confidence": confidence,
    }
    update = {
        "evidence": [item.model_dump(mode="json") for item in merged],
        "evidence_gate": gate,
        "evidence_judgement": {
            "status": gate["status"],
            "verified_count": len(merged),
            "notebook_count": len(internal),
            "web_count": len(staged),
            "evidence_confidence": confidence,
        },
        "evidence_confidence": confidence,
        "source_usage": _source_usage_from_evidence(merged),
        "grounding_report": {
            **dict(state.get("grounding_report") or {}),
            **gate,
        },
    }
    update["trace_records"] = append_trace_record(
        {**state, **update},
        "grade_context",
        context_sufficient=sufficient,
        internal_evidence_confidence=confidence,
        source="augmented_408",
        web_staging_note_count=len(staged),
    )
    return update


def route_after_grade_context(state: QAGraphState) -> str:
    gate = dict(state.get("evidence_gate") or {})
    source_policy = _source_policy(state)
    question = _resolved_question(state)
    boundary = _question_boundary(state, question)
    question_type = str(state.get("question_type") or "")
    if boundary.get("category") == QUESTION_META_TOOL_USAGE or question_type == "meta":
        return "generate_answer_or_question"
    if gate.get("sufficient") and not _should_run_web_retrieval(state, question, source_policy):
        return "generate_answer_or_question"
    if _should_run_web_retrieval(state, question, source_policy) and _can_retry_web(state):
        return "web_query_rewrite"
    if boundary.get("category") == QUESTION_REALTIME_OR_FRESH:
        return "generate_answer_or_question"
    if gate.get("sufficient"):
        return "generate_answer_or_question"
    return "hard_fallback"


def evidence_judge_node(state: QAGraphState) -> dict[str, Any]:
    """Judge whether internal evidence can support the answer before web fallback."""

    _emit_status(
        stream_stage="evidence_judge",
        stage_label="证据评估",
        detail="正在评估内部证据是否足够支撑回答。",
    )
    source_policy = _source_policy(state)
    question = _resolved_question(state)
    all_evidence = _collect_evidence(state)
    notebook_evidence = [
        item
        for item in all_evidence
        if item.source_type in {"notebook", "course"} and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    notebook_required = source_policy == SourcePolicy.NOTEBOOK_ONLY.value or _has_strict_notebook_signal(question)
    if source_policy == SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value and _has_notebook_signal(question):
        notebook_required = True
    confidence = _evidence_confidence(
        state,
        question=question,
        evidence=notebook_evidence,
        source_policy=source_policy,
    )
    sufficient = bool(confidence.get("sufficient"))
    usable = notebook_evidence if sufficient else []
    strong = [item for item in notebook_evidence if item.score >= STRONG_EVIDENCE_SCORE]
    if sufficient and strong:
        status = "strong"
        usable = strong
        reason = "strong_notebook_evidence"
    elif sufficient and usable:
        status = "partial"
        reason = "partial_notebook_evidence"
    elif notebook_evidence:
        status = "low_confidence"
        reason = "low_evidence_confidence"
    else:
        status = "insufficient"
        reason = "no_sufficient_notebook_evidence"

    gate = {
        "sufficient": sufficient,
        "insufficient": notebook_required and not sufficient,
        "source_policy": source_policy,
        "notebook_required": notebook_required,
        "usable_evidence_refs": [item.id for item in usable],
        "usable_evidence_count": len(usable),
        "missing_topic": question,
        "reason": reason,
        "status": status,
        "evidence_confidence": confidence,
    }
    judgement = {
        "status": status,
        "missing_reason": "" if sufficient else reason,
        "verified_count": len(usable),
        "discarded_count": max(0, len(all_evidence) - len(usable)),
        "strong_count": len(strong),
        "partial_count": max(0, len(usable) - len(strong)),
        "notebook_count": len(notebook_evidence),
        "web_count": 0,
        "route_count": len(state.get("knowledge_routes") or []),
        "evidence_confidence": confidence,
    }
    logger.info(
        "QA 证据置信度评估 | request_id={} score={} level={} sufficient={} reason={} usable={} strong={}",
        str(state.get("request_id") or state.get("message_id") or state.get("run_id") or ""),
        confidence.get("score"),
        confidence.get("level"),
        confidence.get("sufficient"),
        confidence.get("reason"),
        len(notebook_evidence),
        len(strong),
    )
    return {
        "trace_records": append_trace_record(
            state,
            "internal_evidence_judge",
            internal_evidence_confidence={
                "score": confidence.get("score"),
                "level": confidence.get("level"),
                "threshold": confidence.get("threshold"),
                "sufficient": confidence.get("sufficient"),
                "reason": confidence.get("reason"),
            },
            usable_evidence_count=len(usable),
            strong_count=len(strong),
            status=status,
        ),
        "evidence": [item.model_dump(mode="json") for item in usable],
        "notebook_evidence": [item.model_dump(mode="json") for item in notebook_evidence],
        "web_evidence": [],
        "evidence_judgement": judgement,
        "evidence_confidence": confidence,
        "retrieval_report": {
            **dict(state.get("retrieval_report") or {}),
            "evidence_confidence": confidence,
        },
        "evidence_gate": gate,
        "grounding_report": {
            **gate,
            "evidence_confidence": confidence,
        },
    }


def route_after_evidence_judge(state: QAGraphState) -> str:
    """Run web fallback only when the judged evidence is insufficient and policy/signals allow it."""

    gate = dict(state.get("evidence_gate") or {})
    source_policy = _source_policy(state)
    question = _resolved_question(state)
    if gate.get("sufficient"):
        if _should_run_web_retrieval(state, question, source_policy):
            return "web_search_if_needed"
        return "evidence_merge"
    if _should_run_web_retrieval(state, question, source_policy):
        return "web_search_if_needed"
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value or bool(gate.get("insufficient")):
        return "insufficient_evidence_response"
    return "evidence_merge"


def external_evidence_judge_node(state: QAGraphState) -> dict[str, Any]:
    """Judge web evidence before it can be merged into answer evidence."""

    _emit_status(
        stream_stage="external_evidence_judge",
        stage_label="外部证据评估",
        detail="正在评估联网证据是否足够可靠。",
    )
    question = _resolved_question(state)
    candidates = _parse_evidence_list(state.get("pending_web_evidence") or state.get("web_evidence") or [])
    web_candidates = [
        item
        for item in candidates
        if item.source_type == "web" and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    confidence = _evidence_confidence(
        state,
        question=question,
        evidence=web_candidates,
        source_policy=SourcePolicy.OPEN_TOOLS.value,
    )
    sufficient = bool(confidence.get("sufficient"))
    usable = web_candidates if sufficient else []
    strong = [item for item in web_candidates if item.score >= STRONG_EVIDENCE_SCORE]
    if sufficient and strong:
        status = "strong"
        reason = "strong_external_evidence"
    elif sufficient and usable:
        status = "partial"
        reason = "partial_external_evidence"
    elif web_candidates:
        status = "low_confidence"
        reason = "low_external_evidence_confidence"
    else:
        status = "insufficient"
        reason = "no_sufficient_external_evidence"

    confidence = {
        **confidence,
        "reason": "external_evidence_confidence_sufficient" if sufficient else reason,
    }
    gate = {
        "sufficient": sufficient,
        "insufficient": not sufficient,
        "source_policy": _source_policy(state),
        "usable_evidence_refs": [item.id for item in usable],
        "usable_evidence_count": len(usable),
        "missing_topic": question,
        "reason": reason,
        "status": status,
        "evidence_confidence": confidence,
    }
    judgement = {
        "status": status,
        "missing_reason": "" if sufficient else reason,
        "verified_count": len(usable),
        "discarded_count": max(0, len(candidates) - len(usable)),
        "strong_count": len(strong),
        "partial_count": max(0, len(usable) - len(strong)),
        "web_count": len(web_candidates),
        "candidate_count": len(candidates),
        "evidence_confidence": confidence,
    }
    logger.info(
        "QA 外部证据置信度评估 | request_id={} score={} level={} sufficient={} reason={} candidates={} strong={}",
        str(state.get("request_id") or state.get("message_id") or state.get("run_id") or ""),
        confidence.get("score"),
        confidence.get("level"),
        confidence.get("sufficient"),
        confidence.get("reason"),
        len(web_candidates),
        len(strong),
    )
    grounding_report = {
        **dict(state.get("grounding_report") or {}),
        "external_evidence_gate": gate,
        "external_evidence_confidence": confidence,
    }
    update: dict[str, Any] = {
        "trace_records": append_trace_record(
            state,
            "external_evidence_judge",
            external_evidence_confidence={
                "score": confidence.get("score"),
                "level": confidence.get("level"),
                "threshold": confidence.get("threshold"),
                "sufficient": confidence.get("sufficient"),
                "reason": confidence.get("reason"),
            },
            usable_evidence_count=len(usable),
            strong_count=len(strong),
            status=status,
        ),
        "web_evidence": [item.model_dump(mode="json") for item in usable],
        "external_evidence_judgement": judgement,
        "external_evidence_confidence": confidence,
        "external_evidence_gate": gate,
        "retrieval_report": {
            **dict(state.get("retrieval_report") or {}),
            "external_evidence_confidence": confidence,
            "external_verified_count": len(usable),
        },
        "grounding_report": grounding_report,
    }
    if sufficient:
        update["evidence_gate"] = {
            **dict(state.get("evidence_gate") or {}),
            "sufficient": True,
            "insufficient": False,
            "external_evidence_sufficient": True,
            "external_evidence_reason": reason,
            "external_evidence_status": status,
            "external_evidence_refs": [item.id for item in usable],
        }
    return update


def route_after_external_evidence_judge(state: QAGraphState) -> str:
    gate = dict(state.get("external_evidence_gate") or {})
    if gate.get("sufficient"):
        return "evidence_merge"
    if not bool(state.get("web_search_attempted")):
        return "evidence_merge"
    return "insufficient_evidence_response"


def insufficient_evidence_response_node(state: QAGraphState) -> dict[str, Any]:
    """Return a final response when required evidence cannot support an answer."""

    source_policy = _source_policy(state)
    question = _resolved_question(state)
    internal_gate = dict(state.get("evidence_gate") or {})
    external_gate = dict(state.get("external_evidence_gate") or {})
    reason = str(external_gate.get("reason") or internal_gate.get("reason") or "insufficient_evidence")
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value or internal_gate.get("notebook_required"):
        answer = (
            "当前资料不足，无法只依据已有 notebook 或课程资料可靠回答这个问题。"
            f"你可以补充与「{question}」相关的资料，或允许我使用外部资料后再试。"
        )
        answer_mode = "insufficient_notebook"
    elif bool(state.get("web_search_attempted")):
        answer = (
            "内部资料和联网补充都还没有足够可靠的证据支撑这个回答。"
            "你可以换个更具体的问题，或稍后重新检索。"
        )
        answer_mode = "insufficient_external_evidence"
    else:
        answer = "我目前缺少足够可靠的证据来给出确定回答。你可以补充更具体的上下文后再问一次。"
        answer_mode = "insufficient_evidence"

    gate = {
        **internal_gate,
        "sufficient": False,
        "insufficient": True,
        "reason": reason,
        "status": "insufficient",
        "missing_topic": question,
        "external_evidence_gate": external_gate,
    }
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        coach_actions=["request_more_evidence"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": answer_mode,
            "degraded": True,
            "source_policy": source_policy,
            "evidence_sufficiency": gate,
            "external_evidence_judgement": dict(state.get("external_evidence_judgement") or {}),
        },
    )
    error = GraphError(
        code="qa_insufficient_evidence",
        message=reason,
        node="insufficient_evidence_response",
        severity=GraphErrorSeverity.WARNING,
        metadata={"source_policy": source_policy},
    )
    return {
        "trace_records": append_trace_record(
            state,
            "final_response",
            final_response_status=answer_mode,
            sufficient_evidence=False,
            reason=reason,
            source_policy=source_policy,
        ),
        "final_response": response.model_dump(mode="json"),
        "source_usage": "model",
        "evidence_gate": gate,
        "grounding_report": {
            **dict(state.get("grounding_report") or {}),
            "insufficient_evidence": gate,
        },
        "errors": [*list(state.get("errors") or []), error.model_dump(mode="json")],
    }


def answer_generate_node(
    state: QAGraphState,
    *,
    adapter: QARuntimeAdapter | None = None,
) -> dict[str, Any]:
    _emit_status(
        stream_stage="answer_generate",
        stage_label="生成回答",
        detail="证据已完成合并，正在生成候选回答。",
    )
    return run_adapter(state, adapter=adapter)


def generate_answer_or_question_node(
    state: QAGraphState,
    *,
    adapter: QARuntimeAdapter | None = None,
) -> dict[str, Any]:
    """Generate the 408 answer candidate; question generation stays in its own graph."""

    generate_retry_count = _bounded_retry_count(state.get("generate_retry_count"), default=0)
    if str((state.get("quality_check") or {}).get("repair_action") or "") == "regenerate":
        generate_retry_count += 1
    update = answer_generate_node(state, adapter=adapter)
    update["generate_retry_count"] = generate_retry_count
    update["trace_records"] = append_trace_record(
        {**state, **update},
        "generate_answer_or_question",
        goal_route=str(state.get("goal_route") or "answer_408"),
        generate_retry_count=generate_retry_count,
        max_generate_retry=_max_generate_retry(state),
    )
    return update


def answer_quality_check_node(state: QAGraphState) -> dict[str, Any]:
    """Check answer quality and decide whether to pass, repair, or clarify."""

    _emit_status(
        stream_stage="answer_quality_check",
        stage_label="质量检查",
        detail="正在检查回答是否有足够证据和稳定结构。",
    )
    source_policy = _source_policy(state)
    final_response = FinalResponse.model_validate(state.get("final_response") or {})
    question = _resolved_question(state)
    evidence = _collect_answer_evidence(state)
    evidence_by_id = {item.id: item for item in evidence}
    web_used = any(item.source_type == "web" for item in evidence)
    notebook_used = any(item.source_type in {"notebook", "course"} for item in evidence)
    issues: list[str] = []
    needs_web = False

    if not final_response.answer.strip() or final_response.answer.strip() == "这一轮没有生成可用回答。":
        issues.append("empty_answer")
    if final_response.evidence_refs and any(ref not in evidence_by_id for ref in final_response.evidence_refs):
        issues.append("evidence_ref_missing")
    answer_mode = str(final_response.ui_payload.get("answer_mode") or "")
    if (
        _has_external_search_signal(question)
        and not web_used
        and not bool(state.get("web_search_attempted"))
        and source_policy != SourcePolicy.NOTEBOOK_ONLY.value
        and answer_mode not in {"realtime_requires_web", "tool_trace_meta"}
    ):
        issues.append("time_sensitive_without_web")
        needs_web = True
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value and final_response.source_level == SourceLevel.NOTEBOOK and not notebook_used:
        issues.append("notebook_claim_without_evidence")

    passed = not issues
    repair_count = int(state.get("repair_count") or state.get("answer_repair_attempt_count") or 0)
    max_repair_count = _max_repair_count(state)
    repair_action = "none"
    if issues:
        repairable = any(issue in {"empty_answer", "evidence_ref_missing"} for issue in issues)
        if repairable and repair_count < max_repair_count:
            repair_action = "rewrite_with_evidence"
        elif any(issue in {"notebook_claim_without_evidence", "time_sensitive_without_web"} for issue in issues):
            repair_action = "ask_clarification"
        else:
            repair_action = "fallback_general_answer"
    status = "pass" if passed else "failed"
    quality_check = {
        "passed": passed,
        "reason": issues[0] if issues else "quality_pass",
        "repair_action": repair_action,
        "issues": issues,
        "repair_count": repair_count,
        "max_repair_count": max_repair_count,
        "repair_attempt_count": repair_count,
        "max_repair_attempts": max_repair_count,
    }
    return {
        "trace_records": append_trace_record(
            state,
            "answer_quality_check",
            answer_quality_status=status,
            passed=passed,
            reason=quality_check["reason"],
            repair_action=repair_action,
            repair_attempt_count=repair_count,
            max_repair_attempts=max_repair_count,
        ),
        "quality_check": quality_check,
        "answer_quality": {
            "status": status,
            "passed": passed,
            "issues": issues,
            "needs_web_search": False,
            "web_search_recommended": needs_web,
            "reason": quality_check["reason"],
            "repair_action": repair_action,
            "web_repair_count": int(state.get("web_search_iteration") or 0),
            "answer_repair_count": repair_count,
            "repair_count": repair_count,
            "max_repair_count": max_repair_count,
        }
    }


def quality_gate_node(state: QAGraphState) -> dict[str, Any]:
    update = answer_quality_check_node(state)
    quality = dict(update.get("quality_check") or {})
    issues = set(quality.get("issues") or [])
    decision = "pass"
    if not quality.get("passed"):
        response = FinalResponse.model_validate(state.get("final_response") or {})
        forced = str(response.ui_payload.get("quality_gate_decision") or "").strip()
        if forced in {"rethink", "regenerate", "web_enrich", "fallback"}:
            decision = forced
        elif "time_sensitive_without_web" in issues and _can_retry_web({**state, **update}):
            decision = "web_enrich"
        elif "empty_answer" in issues or "evidence_ref_missing" in issues:
            decision = "rethink"
        elif str(state.get("question_type") or "") == "practice_generation":
            decision = "regenerate"
        else:
            decision = "fallback"
    update["quality_gate_decision"] = decision
    update["answer_quality"] = {
        **dict(update.get("answer_quality") or {}),
        "quality_gate_decision": decision,
        "web_retry_count": int(state.get("web_retry_count") or 0),
        "max_web_retry": _max_web_retry(state),
        "rethink_retry_count": int(state.get("rethink_retry_count") or 0),
        "max_rethink_retry": _max_rethink_retry(state),
        "generate_retry_count": int(state.get("generate_retry_count") or 0),
        "max_generate_retry": _max_generate_retry(state),
    }
    update["trace_records"] = append_trace_record(
        {**state, **update},
        "quality_gate",
        decision=decision,
        issues=list(issues),
        passed=bool(quality.get("passed")),
    )
    return update


def route_after_answer_quality(state: QAGraphState) -> str:
    quality = dict(state.get("quality_check") or state.get("answer_quality") or {})
    if quality.get("passed") or str(quality.get("status") or "") == "pass":
        return "qa_result_compose"
    action = str(quality.get("repair_action") or "ask_clarification")
    if action == "rewrite_with_evidence":
        return "answer_repair"
    return "qa_clarification_response"


def route_after_quality_gate(state: QAGraphState) -> str:
    decision = str(state.get("quality_gate_decision") or "fallback")
    if decision == "pass":
        return "finalize"
    if decision == "rethink" and _can_retry_rethink(state):
        return "rethink_and_revise"
    if decision == "regenerate" and _can_retry_generate(state):
        return "generate_answer_or_question"
    if decision == "web_enrich" and _can_retry_web(state):
        return "web_query_rewrite"
    return "hard_fallback"


def answer_repair_node(state: QAGraphState) -> dict[str, Any]:
    """Repair a failed candidate answer once, using only merged evidence."""

    attempt_count = int(state.get("repair_count") or state.get("answer_repair_attempt_count") or 0) + 1
    max_repair_count = _max_repair_count(state)
    response = FinalResponse.model_validate(state.get("final_response") or {})
    evidence = _collect_answer_evidence(state)
    source_usage = _source_usage_from_evidence(evidence)
    source_level = _source_level_from_usage(source_usage, response.source_level)
    if not evidence:
        repaired = response.model_copy(
            update={
                "answer": "",
                "source_level": SourceLevel.NONE,
                "evidence_refs": [],
                "ui_payload": {
                    **dict(response.ui_payload),
                    "answer_mode": "answer_repair_no_evidence",
                    "degraded": True,
                    "repair_attempt_count": attempt_count,
                },
            }
        )
        return {
            "trace_records": append_trace_record(
                state,
                "answer_repair",
                repair_attempt_count=attempt_count,
                max_repair_attempts=max_repair_count,
                status="no_evidence",
            ),
            "final_response": repaired.model_dump(mode="json"),
            "repair_count": attempt_count,
            "max_repair_count": max_repair_count,
            "answer_repair_attempt_count": attempt_count,
        }

    lead = evidence[0].text.strip().replace("\n", " ")
    prefix = "结合内部资料和联网信息，" if source_usage == "mixed" else "基于已审核证据，"
    if source_usage == "web":
        prefix = "基于联网补充证据，"
    elif source_usage == "notebook":
        prefix = "参考你的资料，"
    answer = f"{prefix}{lead}"
    if not answer.endswith(("。", ".", "！", "!", "？", "?")):
        answer = f"{answer}。"
    repaired = response.model_copy(
        update={
            "answer": answer,
            "source_level": source_level,
            "evidence_refs": [item.id for item in evidence],
            "ui_payload": {
                **dict(response.ui_payload),
                "answer_mode": "answer_repaired",
                "degraded": True,
                "repair_attempt_count": attempt_count,
                "repair_source_usage": source_usage,
            },
        }
    )
    return {
        "trace_records": append_trace_record(
            state,
            "answer_repair",
            repair_attempt_count=attempt_count,
            max_repair_attempts=max_repair_count,
            status="rewritten",
            source_usage=source_usage,
        ),
        "final_response": repaired.model_dump(mode="json"),
        "repair_count": attempt_count,
        "max_repair_count": max_repair_count,
        "answer_repair_attempt_count": attempt_count,
    }


def rethink_and_revise_node(state: QAGraphState) -> dict[str, Any]:
    rethink_retry_count = _bounded_retry_count(state.get("rethink_retry_count"), default=0) + 1
    update = answer_repair_node(state)
    update["rethink_retry_count"] = rethink_retry_count
    update["trace_records"] = append_trace_record(
        {**state, **update},
        "rethink_and_revise",
        rethink_retry_count=rethink_retry_count,
        max_rethink_retry=_max_rethink_retry(state),
    )
    return update


def qa_clarification_response_node(state: QAGraphState) -> dict[str, Any]:
    """Return a safe clarification/degraded response when quality cannot be repaired."""

    quality = dict(state.get("quality_check") or state.get("answer_quality") or {})
    gate = dict(state.get("evidence_gate") or {})
    source_policy = _source_policy(state)
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        answer = "当前资料里还没有足够证据支撑这个回答。你可以补充相关资料，或允许我使用外部资料后再问一次。"
    else:
        answer = "我目前缺少足够可靠的证据来给出确定回答。你可以补充更具体的上下文，或明确允许联网补充来源。"
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        coach_actions=["ask_clarification"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "clarification_required",
            "degraded": True,
            "answer_quality": quality,
            "evidence_sufficiency": gate,
            "source_policy": source_policy,
        },
    )
    error = GraphError(
        code="qa_clarification_response",
        message=str(quality.get("reason") or "answer_quality_failed"),
        node="qa_clarification_response",
        severity=GraphErrorSeverity.WARNING,
        metadata={"repair_action": str(quality.get("repair_action") or "")},
    )
    return {
        "trace_records": append_trace_record(
            state,
            "final_response",
            final_response_status="clarification_required",
            answer_quality_status=str(quality.get("status") or ""),
            reason=str(quality.get("reason") or "answer_quality_failed"),
            source_policy=source_policy,
        ),
        "final_response": response.model_dump(mode="json"),
        "source_usage": "model",
        "errors": [*list(state.get("errors") or []), error.model_dump(mode="json")],
    }


clarification_response_node = qa_clarification_response_node


def hard_fallback_node(state: QAGraphState) -> dict[str, Any]:
    reason = _hard_fallback_reason(state)
    source_policy = _source_policy(state)
    boundary = _question_boundary(state)
    if boundary.get("category") == QUESTION_REALTIME_OR_FRESH and not bool(state.get("web_search_attempted")):
        response = _realtime_without_web_response(
            question=_resolved_question(state),
            boundary=boundary,
            trace=_build_tool_invocation_trace(state),
        )
        response = response.model_copy(
            update={
                "ui_payload": {
                    **dict(response.ui_payload),
                    "goal_route": str(state.get("goal_route") or "answer_408"),
                    "qa_flow_version": QA_FLOW_VERSION,
                    "hard_fallback_reason": reason,
                }
            }
        )
    else:
        if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
            answer = "当前 408 核心资料不足，且本轮要求只使用内部资料，因此我不能编造答案。请补充资料或关闭 notebook_only 后再试。"
        elif bool(state.get("web_search_attempted")):
            answer = "内部资料和联网补充都没有通过证据质量检查，我不能给出确定答案。你可以换一个更具体的 408 问题后重试。"
        else:
            answer = "当前缺少足够可靠的 408 资料支撑这个回答，我先安全兜底，不编造结论。"
        response = FinalResponse(
            answer=answer,
            source_level=SourceLevel.NONE,
            coach_actions=["request_more_evidence"],
            mastery_signals={"signal_strength": "none"},
            ui_payload={
                "target_graph_type": GraphType.QA.value,
                "answer_mode": "hard_fallback",
                "goal_route": str(state.get("goal_route") or "answer_408"),
                "qa_flow_version": QA_FLOW_VERSION,
                "hard_fallback_reason": reason,
                "source_policy": source_policy,
            },
        )
    error = GraphError(
        code="qa_hard_fallback",
        message=reason,
        node="hard_fallback",
        severity=GraphErrorSeverity.WARNING,
        metadata={"source_policy": source_policy},
    )
    return {
        "trace_records": append_trace_record(
            state,
            "hard_fallback",
            hard_fallback_reason=reason,
            web_retry_count=int(state.get("web_retry_count") or 0),
            rethink_retry_count=int(state.get("rethink_retry_count") or 0),
            generate_retry_count=int(state.get("generate_retry_count") or 0),
        ),
        "final_response": response.model_dump(mode="json"),
        "hard_fallback_reason": reason,
        "source_usage": "model",
        "evidence_gate": {
            **dict(state.get("evidence_gate") or {}),
            "sufficient": False,
            "insufficient": True,
            "reason": reason,
            "status": "hard_fallback",
        },
        "errors": [*list(state.get("errors") or []), error.model_dump(mode="json")],
    }


def finalize_node(state: QAGraphState) -> dict[str, Any]:
    """Compose final QA response metadata and learning events in one diagram node."""

    compose_update = qa_result_compose_node(state)
    working = {**state, **compose_update}
    event_update = compose_learning_events(working) if working.get("final_response") else {}
    final_response = FinalResponse.model_validate(working.get("final_response") or {})
    final_payload = {
        **dict(final_response.ui_payload),
        "qa_flow_version": QA_FLOW_VERSION,
        "goal_route": str(state.get("goal_route") or final_response.ui_payload.get("goal_route") or "answer_408"),
        "web_retry_count": int(state.get("web_retry_count") or 0),
        "max_web_retry": _max_web_retry(state),
        "rethink_retry_count": int(state.get("rethink_retry_count") or 0),
        "max_rethink_retry": _max_rethink_retry(state),
        "generate_retry_count": int(state.get("generate_retry_count") or 0),
        "max_generate_retry": _max_generate_retry(state),
        "web_staging_note_count": len(state.get("web_staging_notes") or []),
        "source_usage": str(working.get("source_usage") or state.get("source_usage") or ""),
    }
    hard_reason = str(state.get("hard_fallback_reason") or "")
    if hard_reason:
        final_payload["hard_fallback_reason"] = hard_reason
    response = final_response.model_copy(update={"ui_payload": final_payload})
    return {
        **compose_update,
        **event_update,
        "final_response": response.model_dump(mode="json"),
        "trace_records": append_trace_record(
            {**working, **event_update, "final_response": response.model_dump(mode="json")},
            "finalize",
            goal_route=final_payload["goal_route"],
            qa_flow_version=QA_FLOW_VERSION,
            web_staging_note_count=final_payload["web_staging_note_count"],
            source_usage=final_payload["source_usage"],
            hard_fallback_reason=hard_reason,
        ),
    }


def should_run_web_search(state: QAGraphState) -> str:
    _ = state
    return "evidence_merge"


def web_search_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Legacy node kept for old callers; production web search now runs in retrieval_node."""

    source_policy = _source_policy(state)
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return {
            "web_search_attempted": False,
            "web_search_reason": "source_policy_notebook_only",
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    question = _resolved_question(state)
    request = _tool_request(
        state,
        capability=ToolCapability.WEB_SEARCH,
        question=question,
        route=None,
        risk_level=ToolRiskLevel.MEDIUM,
        source_policy=source_policy,
    )
    existing_requests = list(state.get("tool_requests") or [])
    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    request_payload = request.model_dump(mode="json")

    if tool_executor is None:
        return {
            "tool_requests": [*existing_requests, request_payload],
            "web_search_attempted": False,
            "web_search_reason": "planned_without_executor",
            "web_search_iteration": int(state.get("web_search_iteration") or 0),
        }

    result = tool_executor.execute(request)
    tagged = _tag_tool_result_evidence(result, route=None, retrieval_source="web")
    return {
        "tool_requests": [*existing_requests, request_payload],
        "tool_results": [*existing_results, tagged.model_dump(mode="json")],
        "web_search_attempted": True,
        "web_search_reason": (state.get("answer_quality") or {}).get("reason") or "quality_fallback",
        "web_search_iteration": int(state.get("web_search_iteration") or 0) + 1,
    }


def evidence_merge_node(state: QAGraphState) -> dict[str, Any]:
    """Merge evidence that has already passed the judge while keeping source classes explicit."""

    _emit_status(
        stream_stage="evidence_merge",
        stage_label="证据合并",
        detail="正在合并内部证据和已触发的联网证据。",
    )
    internal_evidence = _collect_explicit_evidence(state)
    web_evidence = _parse_evidence_list(state.get("web_evidence") or [])
    notebook = [
        item
        for item in internal_evidence
        if item.source_type in {"notebook", "course"} and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    web = [item for item in web_evidence if item.source_type == "web" and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE]
    merged = _dedupe_evidence([*notebook, *web])
    source_usage = "model"
    if notebook and web:
        source_usage = "mixed"
    elif notebook:
        source_usage = "notebook"
    elif web:
        source_usage = "web"
    return {
        "evidence": [item.model_dump(mode="json") for item in merged],
        "notebook_evidence": [item.model_dump(mode="json") for item in notebook],
        "web_evidence": [item.model_dump(mode="json") for item in web],
        "source_usage": source_usage,
    }


def qa_result_compose_node(state: QAGraphState) -> dict[str, Any]:
    """Compose the final contract response with v2 QA process metadata."""

    response = FinalResponse.model_validate(state.get("final_response") or {})
    evidence = _collect_answer_evidence(state)
    source_usage = str(state.get("source_usage") or _source_usage_from_evidence(evidence))
    source_level = _source_level_from_usage(source_usage, response.source_level)
    evidence_refs = [item.id for item in evidence]
    answer = response.answer
    tool_invocation_trace = _build_tool_invocation_trace(state)

    if not answer.strip() and evidence:
        lead = evidence[0].text.strip().replace("\n", " ")
        prefix = "基于外部来源补充，" if source_usage == "web" else "参考你的资料，"
        answer = f"{prefix}{lead}"
    elif source_usage == "web" and dict(state.get("answer_quality") or {}).get("needs_web_search") and evidence:
        lead = evidence[0].text.strip().replace("\n", " ")
        answer = f"基于外部来源补充，{lead}"
    elif source_usage == "mixed" and dict(state.get("answer_quality") or {}).get("needs_web_search") and evidence:
        lead = evidence[0].text.strip().replace("\n", " ")
        answer = f"结合你的资料和外部来源，{lead}"

    update_errors = list(state.get("errors") or [])
    if not answer.strip():
        answer = "我暂时没有足够信息给出可靠回答。你可以补充更具体的问题或相关资料。"
        update_errors.append(
            GraphError(
                code="qa_empty_answer",
                message="QAGraph produced an empty answer.",
                node="final_response",
                severity=GraphErrorSeverity.WARNING,
            ).model_dump(mode="json")
        )
    answer = _clean_fact_boundary_answer(answer, state)

    ui_payload = {
        **dict(response.ui_payload),
        "chat_question_graph_version": "v2",
        "qa_flow_version": str(state.get("qa_flow_version") or QA_FLOW_VERSION),
        "goal_route": str(state.get("goal_route") or "answer_408"),
        "question_boundary": _question_boundary(state),
        "intent_result": dict(state.get("intent_result") or {}),
        "knowledge_routes": list(state.get("knowledge_routes") or []),
        "retrieval_skipped_reason": str(state.get("retrieval_skipped_reason") or ""),
        "retrieval_report": dict(state.get("retrieval_report") or {}),
        "evidence_judgement": dict(state.get("evidence_judgement") or {}),
        "evidence_confidence": dict(state.get("evidence_confidence") or {}),
        "external_evidence_judgement": dict(state.get("external_evidence_judgement") or {}),
        "external_evidence_confidence": dict(state.get("external_evidence_confidence") or {}),
        "answer_quality": dict(state.get("answer_quality") or {}),
        "quality_check": dict(state.get("quality_check") or {}),
        "repair_count": int(state.get("repair_count") or state.get("answer_repair_attempt_count") or 0),
        "max_repair_count": _max_repair_count(state),
        "answer_repair_attempt_count": int(state.get("answer_repair_attempt_count") or 0),
        "web_retry_count": int(state.get("web_retry_count") or 0),
        "max_web_retry": _max_web_retry(state),
        "rethink_retry_count": int(state.get("rethink_retry_count") or 0),
        "max_rethink_retry": _max_rethink_retry(state),
        "generate_retry_count": int(state.get("generate_retry_count") or 0),
        "max_generate_retry": _max_generate_retry(state),
        "web_staging_note_count": len(state.get("web_staging_notes") or []),
        "hard_fallback_reason": str(state.get("hard_fallback_reason") or ""),
        "source_usage": source_usage,
        "web_search_attempted": bool(state.get("web_search_attempted")),
        "tool_invocation_trace": tool_invocation_trace,
        "concept_linking": dict(state.get("concept_linking") or {}),
    }
    concepts = list(response.concepts)
    concept_linking = dict(state.get("concept_linking") or {})
    if not concepts and concept_linking.get("status") == "matched" and concept_linking.get("concept_id"):
        concepts = [
            ConceptRef(
                concept_id=str(concept_linking.get("concept_id") or ""),
                name=str(concept_linking.get("concept_name") or concept_linking.get("concept_id") or ""),
                confidence=float(concept_linking.get("confidence") or 0.0),
                source="concept_registry",
            )
        ]
    final_response = response.model_copy(
        update={
            "answer": answer,
            "source_level": source_level,
            "concepts": concepts,
            "evidence_refs": evidence_refs,
            "ui_payload": ui_payload,
        }
    )
    return {
        "trace_records": append_trace_record(
            state,
            "final_response",
            final_response_status="completed",
            source_usage=source_usage,
            source_level=source_level.value if hasattr(source_level, "value") else str(source_level),
            web_search_used=bool(tool_invocation_trace.get("didUseWebSearch")),
            answer_quality_status=str(dict(state.get("answer_quality") or {}).get("status") or ""),
            repair_attempt_count=int(state.get("answer_repair_attempt_count") or 0),
        ),
        "final_response": final_response.model_dump(mode="json"),
        "errors": update_errors,
        "tool_invocation_trace": tool_invocation_trace,
        "web_search_used": bool(tool_invocation_trace.get("didUseWebSearch")),
    }


final_response_node = qa_result_compose_node


def prepare_qa_request(state: QAGraphState) -> dict[str, Any]:
    question = _question(state)
    source_policy = _source_policy(state)
    question_type = str(state.get("question_type") or _infer_question_type(question))
    return {
        "run_id": str(state.get("run_id") or uuid4()),
        "graph_type": GraphType.QA.value,
        "graph_version": str(state.get("graph_version") or GRAPH_VERSION),
        "source_policy": source_policy,
        "user_message": question,
        "messages": list(state.get("messages") or [{"role": "user", "content": question}]),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "qa_request": {
            "question": question,
            "question_type": question_type,
            "user_id": str(state.get("user_id") or ""),
            "thread_id": state.get("thread_id"),
            "notebook_id": state.get("notebook_id"),
            "course_id": state.get("course_id"),
            "source_policy": source_policy,
        },
    }


def evidence_sufficiency_gate(state: QAGraphState) -> dict[str, Any]:
    source_policy = _source_policy(state)
    evidence = _collect_evidence(state)
    usable = [item for item in evidence if item.text.strip() and item.score >= MIN_EVIDENCE_SCORE]
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        usable = [item for item in usable if item.source_type in {"notebook", "course"}]

    sufficient = bool(usable)
    insufficient = source_policy == SourcePolicy.NOTEBOOK_ONLY.value and not sufficient
    gate = {
        "sufficient": sufficient,
        "insufficient": insufficient,
        "source_policy": source_policy,
        "usable_evidence_refs": [item.id for item in usable],
        "usable_evidence_count": len(usable),
        "missing_topic": _question(state),
        "reason": "usable_evidence_found" if sufficient else "no_sufficient_verified_evidence",
    }
    return {
        "evidence": [item.model_dump(mode="json") for item in usable],
        "evidence_gate": gate,
        "grounding_report": gate,
    }


def tool_planner(state: QAGraphState) -> dict[str, Any]:
    gate = dict(state.get("evidence_gate") or {})
    if gate.get("sufficient"):
        return {"tool_requests": []}

    source_policy = _source_policy(state)
    question = _question(state)
    web_search_requested = _web_search_requested_for_state(state)
    capabilities: list[ToolCapability] = []
    if source_policy in {SourcePolicy.NOTEBOOK_ONLY.value, SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value}:
        capabilities.append(ToolCapability.NOTEBOOK_RETRIEVE)
    elif _has_notebook_signal(question):
        capabilities.append(ToolCapability.NOTEBOOK_RETRIEVE)

    if source_policy == SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value and (
        web_search_requested or _has_external_search_signal(question)
    ):
        capabilities.append(ToolCapability.WEB_SEARCH)
    elif source_policy == SourcePolicy.OPEN_TOOLS.value and (
        web_search_requested or _has_external_search_signal(question)
    ):
        capabilities.append(ToolCapability.WEB_SEARCH)

    if not capabilities:
        return {"tool_requests": []}

    requests = [
        ToolExecutionRequest(
            capability=capability,
            input={
                "query": question,
                "notebook_id": state.get("notebook_id"),
                "subject_id": state.get("notebook_id") or state.get("course_id"),
                "user_id": state.get("user_id"),
            },
            input_summary=question,
            user_id=str(state.get("user_id") or ""),
            tenant_id=state.get("tenant_id"),
            source_policy=source_policy,
            risk_level=ToolRiskLevel.LOW,
            test_mode=bool(state.get("test_mode", False)),
            runtime_context={
                "graph_type": GraphType.QA.value,
                "graph_run_id": str(state.get("run_id") or ""),
                "subject_id": state.get("notebook_id") or state.get("course_id"),
                "notebook_id": state.get("notebook_id"),
                "memory": state.get("memory") or {},
                "short_term_messages": list(state.get("messages") or []),
                "session_memory": state.get("session_memory") or {},
            },
        ).model_dump(mode="json")
        for capability in capabilities
    ]
    return {"tool_requests": requests}


def run_adapter(
    state: QAGraphState,
    *,
    adapter: QARuntimeAdapter | None = None,
) -> dict[str, Any]:
    runtime_adapter = adapter or DeterministicQARuntimeAdapter()
    qa_request = dict(state.get("qa_request") or {})
    question = str(qa_request.get("question") or _question(state))
    question_type = str(qa_request.get("question_type") or _infer_question_type(_question(state)))
    source_policy = _source_policy(state)
    evidence = _collect_answer_evidence(state)
    evidence_gate = dict(state.get("evidence_gate") or {})
    boundary = _question_boundary(state, question)
    trace = _build_tool_invocation_trace(state)

    if boundary.get("category") == QUESTION_META_TOOL_USAGE:
        response = _meta_tool_usage_response(
            state,
            question=question,
            previous_trace=state.get("previous_tool_invocation_trace") if isinstance(state.get("previous_tool_invocation_trace"), dict) else None,
            current_trace=trace,
        )
        return {
            "final_response": response.model_dump(mode="json"),
            "source_usage": "model",
            "tool_invocation_trace": trace,
            "runtime_summary": {"answer_mode": "tool_trace_meta"},
        }

    if boundary.get("category") == QUESTION_REALTIME_OR_FRESH and not trace.get("didUseWebSearch"):
        response = _realtime_without_web_response(
            question=question,
            boundary=boundary,
            trace=trace,
        )
        return {
            "final_response": response.model_dump(mode="json"),
            "source_usage": "model",
            "tool_invocation_trace": trace,
            "runtime_summary": {"answer_mode": "realtime_requires_web"},
        }

    contract_runner = getattr(runtime_adapter, "answer_with_contract", None)
    if callable(contract_runner):
        contract_result = contract_runner(
            question=question,
            question_type=question_type,
            source_policy=source_policy,
            evidence=evidence,
            evidence_gate=evidence_gate,
            user_id=str(state.get("user_id") or ""),
            graph_run_id=str(state.get("run_id") or ""),
        )
        update: dict[str, Any] = {
            "final_response": contract_result.final_response.model_dump(mode="json"),
            "runtime_summary": dict(contract_result.runtime_summary),
            "source_usage": _source_usage_from_evidence(evidence),
            "tool_invocation_trace": trace,
        }
        if contract_result.evidence:
            if state.get("evidence_judgement"):
                judged_ids = {item.id for item in evidence}
                judged_runtime_evidence = [item for item in contract_result.evidence if item.id in judged_ids]
                if judged_runtime_evidence:
                    update["evidence"] = [item.model_dump(mode="json") for item in judged_runtime_evidence]
                else:
                    sanitized_response = contract_result.final_response.model_copy(
                        update={
                            "source_level": SourceLevel.MODEL,
                            "evidence_refs": [],
                        }
                    )
                    update["final_response"] = sanitized_response.model_dump(mode="json")
            else:
                update["evidence"] = [item.model_dump(mode="json") for item in contract_result.evidence]
        if contract_result.tool_results:
            existing_tool_results = [
                item.model_dump(mode="json")
                for item in _collect_tool_results(state)
            ]
            update["tool_results"] = [
                *existing_tool_results,
                *[item.model_dump(mode="json") for item in contract_result.tool_results],
            ]
            if any(item.capability == ToolCapability.WEB_SEARCH for item in contract_result.tool_results):
                update["web_search_attempted"] = True
                update["web_search_reason"] = str(state.get("web_search_reason") or "runtime_tool_result")
        if contract_result.learning_events:
            update["adapter_learning_events"] = [
                item.model_dump(mode="json") for item in contract_result.learning_events
            ]
        if contract_result.errors:
            existing_errors = list(state.get("errors") or [])
            update["errors"] = [
                *existing_errors,
                *[item.model_dump(mode="json") for item in contract_result.errors],
            ]
        update["tool_invocation_trace"] = _build_tool_invocation_trace({**state, **update})
        return update

    response = runtime_adapter.answer(
        question=question,
        question_type=question_type,
        source_policy=source_policy,
        evidence=evidence,
        evidence_gate=evidence_gate,
        user_id=str(state.get("user_id") or ""),
        graph_run_id=str(state.get("run_id") or ""),
    )
    return {
        "final_response": response.model_dump(mode="json"),
        "source_usage": _source_usage_from_evidence(evidence),
        "tool_invocation_trace": trace,
    }


def _meta_tool_usage_response(
    state: QAGraphState,
    *,
    question: str,
    previous_trace: dict[str, Any] | None,
    current_trace: dict[str, Any],
) -> FinalResponse:
    _ = (state, question)
    trace = _normalize_tool_invocation_trace(previous_trace or {}) if previous_trace else None
    if trace is None:
        answer = "我没有找到上一轮的工具调用记录，因此不能可靠确认刚刚是否联网搜索。"
        trace_summary = {"trace_available": False}
    else:
        tool_count = int(trace.get("toolCallCount") or 0)
        did_web = bool(trace.get("didUseWebSearch"))
        did_any = bool(trace.get("didUseAnyTool"))
        if did_web:
            answer = f"有。根据刚刚那轮的运行记录，工具调用次数是 {tool_count}，其中包含联网搜索。"
        elif tool_count == 0:
            answer = "没有。根据刚刚那轮的运行记录，工具调用次数是 0，因此没有调用联网搜索。"
        elif did_any:
            answer = f"没有联网搜索。根据刚刚那轮的运行记录，工具调用次数是 {tool_count}，但没有 web_search / 联网搜索调用。"
        else:
            answer = "没有。根据刚刚那轮的运行记录，没有发现联网搜索调用。"
        answer += " HTTP 属于稳定基础知识，所以那轮可以直接基于通用知识回答；这只是补充说明，真正依据是运行记录。"
        trace_summary = {"trace_available": True, **trace}
    return FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        coach_actions=["report_tool_trace"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "tool_trace_meta",
            "tool_invocation_trace": current_trace,
            "previous_tool_invocation_trace": trace_summary,
        },
    )


def _realtime_without_web_response(
    *,
    question: str,
    boundary: dict[str, Any],
    trace: dict[str, Any],
) -> FinalResponse:
    current_date = trace.get("currentDate")
    if boundary.get("contains_relative_year") and current_date is None:
        answer = (
            "这是实时问题，但我无法确定你说的“今年”是哪一年；请补充年份，"
            "或启用联网检索后我再核查官方来源。"
        )
    else:
        has_tool = bool(trace.get("hasWebSearchTool"))
        enabled = bool(trace.get("webSearchEnabled"))
        if not has_tool or not enabled:
            availability = "我当前没有启用联网检索"
        else:
            availability = "本轮没有取得联网检索结果"
        if "gpt" in question.lower() or "openai" in question.lower() or "ChatGPT" in question or "模型" in question:
            topic = "今年 GPT/ChatGPT/OpenAI 模型发布到了哪个版本"
        else:
            topic = "这个当前状态"
        answer = (
            f"这是实时问题，{availability}，不能可靠确认{topic}。"
            "若只基于我的知识截止时间，我不能把它当作当前事实。"
            "需要联网核查官方发布页、官方文档或权威来源后，才能给出确定答案。"
        )
    return FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        coach_actions=["require_web_verification"],
        mastery_signals={"signal_strength": "none", "volatile": True},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "realtime_requires_web",
            "question_boundary": boundary,
            "tool_invocation_trace": trace,
            "volatile_fact": True,
        },
    )


def _clean_fact_boundary_answer(answer: str, state: QAGraphState) -> str:
    """Remove internal retrieval/realtime scaffolding from user-visible answers."""

    text = str(answer or "").strip()
    if not text:
        return ""
    boundary = _question_boundary(state)
    source_policy = _source_policy(state)
    preserve_notebook_notice = (
        source_policy == SourcePolicy.NOTEBOOK_ONLY.value
        or _has_notebook_signal(_question(state))
    )
    if not preserve_notebook_notice:
        text = re.sub(
            r"(当前\s*)?notebook\s*未命中足够相关的资料[，,]\s*下面先按通用知识解释[。.]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(你的资料|当前资料|当前笔记|当前 notebook)\s*(中)?\s*(没有|未找到|未命中)足够相关(的)?(内容|资料)[，,]\s*(我)?先(按|基于)通用知识(解释|说明)[。.]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
    if boundary.get("category") == QUESTION_REALTIME_OR_FRESH and not _build_tool_invocation_trace(state).get("didUseWebSearch"):
        text = re.sub(r"目前公开信息中[，,]?", "", text)
        text = re.sub(r"截至目前[，,]?", "", text)
    text = _dedupe_adjacent_sentences(text)
    text = _dedupe_adjacent_paragraphs(text)
    return text.strip()


def _dedupe_adjacent_paragraphs(text: str) -> str:
    paragraphs = re.split(r"\n{2,}", text)
    deduped: list[str] = []
    previous = ""
    for paragraph in paragraphs:
        current = paragraph.strip()
        if not current:
            continue
        normalized = re.sub(r"\s+", "", current)
        if normalized and normalized != previous:
            deduped.append(current)
            previous = normalized
    return "\n\n".join(deduped)


def _dedupe_adjacent_sentences(text: str) -> str:
    parts = re.split(r"(?<=[。！？.!?])(\s*)", text)
    if len(parts) <= 1:
        return text
    rebuilt: list[str] = []
    previous = ""
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        normalized = re.sub(r"\s+", "", sentence)
        if normalized and normalized == previous:
            continue
        rebuilt.append(sentence)
        rebuilt.append(separator)
        if normalized:
            previous = normalized
    return "".join(rebuilt).strip()


def execute_tool_requests(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    if tool_executor is None:
        return {}

    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    new_results: list[ToolResult] = []
    for raw_request in list(state.get("tool_requests") or []):
        request = ToolExecutionRequest.model_validate(raw_request)
        new_results.append(tool_executor.execute(request))

    if not new_results:
        return {}

    merged_results = [*existing_results, *[item.model_dump(mode="json") for item in new_results]]
    merged_evidence = _collect_evidence({**state, "tool_results": merged_results})
    update: dict[str, Any] = {"tool_results": merged_results}
    usable = [item for item in merged_evidence if item.text.strip() and item.score >= MIN_EVIDENCE_SCORE]
    if usable:
        update["evidence"] = [item.model_dump(mode="json") for item in usable]
        update["evidence_gate"] = {
            **dict(state.get("evidence_gate") or {}),
            "sufficient": True,
            "insufficient": False,
            "usable_evidence_refs": [item.id for item in usable],
            "usable_evidence_count": len(usable),
            "reason": "usable_tool_evidence_found",
        }
        update["grounding_report"] = update["evidence_gate"]
    return update


def compose_learning_events(state: QAGraphState) -> dict[str, Any]:
    response = FinalResponse.model_validate(state.get("final_response") or {})
    qa_request = dict(state.get("qa_request") or {})
    source_policy = _source_policy(state)
    user_id = str(state.get("user_id") or "")
    graph_run_id = str(state.get("run_id") or "")
    message_source_id = _qa_message_source_id(state)
    tool_result_refs = [item.tool_id for item in _collect_tool_results(state)]
    boundary = _question_boundary(state, str(qa_request.get("question") or _question(state)))
    trace = _build_tool_invocation_trace(state)
    is_volatile_fact = boundary.get("category") == QUESTION_REALTIME_OR_FRESH
    base_payload = {
        "question_type": str(qa_request.get("question_type") or _infer_question_type(_question(state))),
        "question_boundary": boundary.get("category"),
        "source_level": response.source_level.value,
        "source_policy": source_policy,
        "answer_mode": str(response.ui_payload.get("answer_mode") or ""),
        "evidence_refs": list(response.evidence_refs),
        "tool_result_refs": tool_result_refs,
        "tool_call_count": trace.get("toolCallCount"),
        "did_use_web_search": trace.get("didUseWebSearch"),
        "current_date": trace.get("currentDate"),
        "volatile": is_volatile_fact,
        "degraded": bool((state.get("evidence_gate") or {}).get("insufficient")),
    }
    events = _adapter_events_from_state(state)
    events.append(
        build_learning_event(
            event_type=LearningEventType.QUESTION_ANSWERED.value,
            user_id=user_id,
            graph_run_id=graph_run_id,
            payload=base_payload,
            source_object_type="chat_message",
            source_object_id=message_source_id,
        )
    )

    if (state.get("evidence_gate") or {}).get("insufficient"):
        events.append(
            build_learning_event(
                event_type=LearningEventType.INSUFFICIENT_EVIDENCE.value,
                user_id=user_id,
                graph_run_id=graph_run_id,
                payload={
                    "missing_topic": _question(state),
                    "source_policy": source_policy,
                    "reason": (state.get("evidence_gate") or {}).get("reason"),
                },
                source_object_type="qa_evidence_gate",
                source_object_id=message_source_id,
            )
        )

    answer_mode = str(response.ui_payload.get("answer_mode") or "")
    if answer_mode in {"answer_repaired", "clarification_required"}:
        events.append(
            build_learning_event(
                event_type=LearningEventType.ANSWER_REPAIRED.value,
                user_id=user_id,
                graph_run_id=graph_run_id,
                payload={
                    "answer_mode": answer_mode,
                    "repair_count": int(state.get("repair_count") or state.get("answer_repair_attempt_count") or 0),
                    "max_repair_count": _max_repair_count(state),
                    "repair_attempt_count": int(state.get("answer_repair_attempt_count") or 0),
                    "quality_check": dict(state.get("quality_check") or {}),
                },
                source_object_type="qa_answer",
                source_object_id=f"{message_source_id}:repair",
            )
        )

    for concept in response.concepts:
        events.append(
            build_learning_event(
                event_type=LearningEventType.CONCEPT_EXPLAINED.value,
                user_id=user_id,
                concept_id=concept.concept_id,
                graph_run_id=graph_run_id,
                payload={
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "confidence": concept.confidence,
                    "source_level": response.source_level.value,
                    "evidence_refs": list(response.evidence_refs),
                    "question_boundary": boundary.get("category"),
                    "volatile": is_volatile_fact,
                    "timestamp": trace.get("currentDate") if is_volatile_fact else None,
                    "did_use_web_search": trace.get("didUseWebSearch"),
                },
                source_object_type="chat_message",
                source_object_id=message_source_id,
            )
        )

    evidence_by_id = {item.id: item for item in _collect_answer_evidence(state)}
    for evidence_ref in response.evidence_refs:
        evidence = evidence_by_id.get(evidence_ref)
        if evidence is None:
            continue
        events.append(
            build_learning_event(
                event_type=LearningEventType.EVIDENCE_USED.value,
                user_id=user_id,
                concept_id=evidence.concepts[0].concept_id if evidence.concepts else None,
                graph_run_id=graph_run_id,
                payload={
                    "evidence_id": evidence.id,
                    "source_type": evidence.source_type,
                    "score": evidence.score,
                    "grounding_status": "used",
                },
                source_object_type="evidence",
                source_object_id=f"{message_source_id}:{evidence.id}",
            )
        )

    for tool_result in _collect_tool_results(state):
        if tool_result.status.value != "success":
            continue
        if tool_result.capability not in {ToolCapability.NOTEBOOK_RETRIEVE, ToolCapability.WEB_SEARCH, ToolCapability.WEB_EXTRACT}:
            continue
        events.append(
            build_learning_event(
                event_type=LearningEventType.TOOL_FALLBACK_USED.value,
                user_id=user_id,
                graph_run_id=graph_run_id,
                payload={
                    "capability": tool_result.capability.value,
                    "source": _public_source_from_capability(tool_result.capability),
                    "tool_result_id": tool_result.tool_id,
                    "evidence_count": len(tool_result.evidence),
                },
                source_object_type="tool_result",
                source_object_id=f"{message_source_id}:{tool_result.tool_id}",
            )
        )

    return {"learning_events": [item.model_dump(mode="json") for item in _events_with_idempotency(events, state)]}


def _normalized_question(state: QAGraphState) -> str:
    return str(state.get("normalized_question") or _question(state)).strip()


def _resolved_question(state: QAGraphState) -> str:
    return str(state.get("resolved_question") or _normalized_question(state)).strip()


def _question(state: QAGraphState) -> str:
    return str(state.get("user_message") or state.get("question") or "").strip()


def _qa_message_source_id(state: QAGraphState) -> str:
    explicit = str(state.get("message_id") or state.get("request_id") or "").strip()
    if explicit:
        return f"qa_message:{explicit}"
    session_id = str(state.get("thread_id") or state.get("session_id") or state.get("user_id") or "").strip()
    question_digest = hashlib.sha256(_normalized_question(state).encode("utf-8")).hexdigest()[:16]
    return f"qa_message:{session_id or 'unknown'}:{question_digest}"


def _public_source_from_capability(capability: ToolCapability) -> str:
    if capability in {ToolCapability.WEB_SEARCH, ToolCapability.WEB_EXTRACT}:
        return "web"
    if capability == ToolCapability.NOTEBOOK_RETRIEVE:
        return "notebook"
    return "tool"


def _source_policy(state: QAGraphState) -> str:
    raw = str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value).strip()
    compatibility_map = {
        "notebook": SourcePolicy.NOTEBOOK_ONLY.value,
        "web": SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
        "mixed": SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
        "none": SourcePolicy.OPEN_TOOLS.value,
        "": SourcePolicy.OPEN_TOOLS.value,
    }
    candidate = compatibility_map.get(raw, raw)
    if candidate == SourcePolicy.OPEN_TOOLS.value:
        question = _question(state)
        if _has_strict_notebook_signal(question):
            return SourcePolicy.NOTEBOOK_ONLY.value
        if _has_notebook_signal(question):
            return SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    try:
        return SourcePolicy(candidate).value
    except ValueError:
        return SourcePolicy.OPEN_TOOLS.value


def _runtime_time_context(state: QAGraphState) -> dict[str, Any]:
    raw = state.get("runtime_time_context")
    if isinstance(raw, dict):
        timezone = raw.get("timezone")
        return {
            "currentDate": raw.get("currentDate"),
            "timezone": str(timezone or _default_timezone()),
            "knowledgeCutoff": raw.get("knowledgeCutoff") or os.getenv("KNOWLEDGE_CUTOFF") or None,
        }
    timezone = _default_timezone()
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        timezone = "UTC"
        now = datetime.now(ZoneInfo("UTC"))
    return {
        "currentDate": now.date().isoformat(),
        "timezone": timezone,
        "knowledgeCutoff": os.getenv("KNOWLEDGE_CUTOFF") or None,
    }


def _default_timezone() -> str:
    return str(os.getenv("APP_TIMEZONE") or os.getenv("TZ") or "Asia/Shanghai").strip() or "Asia/Shanghai"


def _question_boundary(state: QAGraphState, question: str | None = None) -> dict[str, Any]:
    existing = state.get("question_boundary")
    if isinstance(existing, dict) and existing.get("category"):
        return existing
    time_context = _runtime_time_context(state)
    return classify_question_boundary(
        str(question or _normalized_question(state)),
        current_date=time_context.get("currentDate"),
    ).as_dict()


def _tool_executor_has_web_search(tool_executor: ToolExecutor | None) -> bool:
    if tool_executor is None:
        return False
    registry = getattr(tool_executor, "registry", None)
    if registry is None:
        return True
    finder = getattr(registry, "find_by_capability", None)
    if not callable(finder):
        return True
    try:
        return finder(ToolCapability.WEB_SEARCH) is not None
    except Exception:
        return True


def _web_search_requested_for_state(state: QAGraphState | dict[str, Any]) -> bool:
    if bool(state.get("web_search_requested") or state.get("allow_web")):
        return True
    runtime_context = state.get("chat_runtime_context") or state.get("runtime_context") or {}
    if isinstance(runtime_context, dict):
        return bool(runtime_context.get("web_search_requested") or runtime_context.get("allow_web"))
    return False


def _web_search_enabled_for_state(state: QAGraphState | dict[str, Any], *, has_web_search_tool: bool) -> bool:
    if not has_web_search_tool:
        return False
    source_policy = _source_policy(state)  # type: ignore[arg-type]
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return False
    runtime_context = state.get("chat_runtime_context") or state.get("runtime_context") or {}
    if isinstance(runtime_context, dict):
        guard = runtime_context.get("guard") if isinstance(runtime_context.get("guard"), dict) else {}
        if guard.get("allow_search") is False or runtime_context.get("allow_search") is False:
            return False
    return source_policy in {SourcePolicy.OPEN_TOOLS.value, SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value}


def _web_search_reason_for_state(state: QAGraphState | dict[str, Any], *, question: str) -> str:
    existing = str(state.get("web_search_reason") or "").strip()
    if existing and existing != "not_requested_before_evidence_judge":
        return existing
    if _web_search_requested_for_state(state):
        return "client_requested_web_search"
    if _has_external_search_signal(question):
        return "explicit_external_search_signal"
    gate = dict(state.get("evidence_gate") or {})
    if gate.get("reason"):
        return str(gate.get("reason"))
    return "no_sufficient_notebook_evidence"


def _build_tool_invocation_trace(state: QAGraphState) -> dict[str, Any]:
    time_context = _runtime_time_context(state)
    has_web_search_tool = bool(state.get("has_web_search_tool"))
    web_search_enabled = bool(state.get("web_search_enabled"))
    calls: list[dict[str, Any]] = []
    for result in _collect_tool_results(state):
        name = result.capability.value
        status = result.status.value
        calls.append(
            {
                "name": name,
                "type": _public_source_from_capability(result.capability),
                "status": status,
            }
        )
    for raw in list(state.get("external_tool_calls") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("capability") or raw.get("name") or raw.get("tool") or "").strip()
        if not name:
            continue
        status = str(raw.get("status") or ("success" if raw.get("success") is True else ""))
        calls.append(
            {
                "name": name,
                "type": "web" if "search" in name.lower() or str(raw.get("provider") or "").lower() in {"mcp", "tavily", "web"} else "tool",
                "status": status or "unknown",
            }
        )
    did_use_web = any(
        call.get("type") == "web"
        and ("search" in str(call.get("name") or "").lower() or str(call.get("name") or "") == ToolCapability.WEB_SEARCH.value)
        and str(call.get("status") or "") == ToolStatus.SUCCESS.value
        for call in calls
    ) or bool(state.get("web_search_used"))
    return {
        "currentDate": time_context.get("currentDate"),
        "timezone": time_context.get("timezone"),
        "knowledgeCutoff": time_context.get("knowledgeCutoff"),
        "hasWebSearchTool": has_web_search_tool,
        "webSearchEnabled": web_search_enabled,
        "toolCallCount": len(calls),
        "toolCalls": calls,
        "didUseWebSearch": did_use_web,
        "didUseAnyTool": bool(calls),
    }


def _previous_assistant_tool_trace(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        trace = message.get("toolInvocationTrace")
        if isinstance(trace, dict):
            return _normalize_tool_invocation_trace(trace)
        process = message.get("process")
        if isinstance(process, dict):
            tool_calls = process.get("toolCalls")
            if isinstance(tool_calls, list):
                calls = []
                for raw in tool_calls:
                    if not isinstance(raw, dict):
                        continue
                    name = str(raw.get("capability") or raw.get("name") or raw.get("tool") or "").strip()
                    status = str(raw.get("status") or "").strip() or "unknown"
                    calls.append(
                        {
                            "name": name,
                            "type": "web" if "search" in name.lower() else "tool",
                            "status": status,
                        }
                    )
                if calls:
                    did_use_web = any(call["type"] == "web" and call["status"] == ToolStatus.SUCCESS.value for call in calls)
                    return {
                        "currentDate": None,
                        "timezone": None,
                        "knowledgeCutoff": None,
                        "hasWebSearchTool": False,
                        "webSearchEnabled": False,
                        "toolCallCount": len(calls),
                        "toolCalls": calls,
                        "didUseWebSearch": did_use_web,
                        "didUseAnyTool": True,
                    }
    return None


def _normalize_tool_invocation_trace(raw: dict[str, Any]) -> dict[str, Any]:
    calls = raw.get("toolCalls") if isinstance(raw.get("toolCalls"), list) else []
    tool_call_count = int(raw.get("toolCallCount") or len(calls) or 0)
    return {
        "currentDate": raw.get("currentDate"),
        "timezone": raw.get("timezone"),
        "knowledgeCutoff": raw.get("knowledgeCutoff"),
        "hasWebSearchTool": bool(raw.get("hasWebSearchTool")),
        "webSearchEnabled": bool(raw.get("webSearchEnabled")),
        "toolCallCount": tool_call_count,
        "toolCalls": [dict(item) for item in calls if isinstance(item, dict)],
        "didUseWebSearch": bool(raw.get("didUseWebSearch")),
        "didUseAnyTool": bool(raw.get("didUseAnyTool") or tool_call_count > 0),
    }


def _infer_question_type(question: str) -> str:
    lightweight_intent = classify_lightweight_answer_intent(question)
    if lightweight_intent == "simple_fact":
        return "simple_fact"
    if lightweight_intent == "practice_generation":
        return "practice_generation"
    normalized = question.lower()
    if any(token in question for token in ("什么是", "什么叫", "解释", "概念")):
        return "concept"
    if any(token in normalized for token in ("what is", "define", "explain")):
        return "concept"
    return "qa"


def _infer_intent(question: str) -> str:
    normalized = question.lower()
    lightweight_intent = classify_lightweight_answer_intent(question)
    if lightweight_intent == "simple_fact":
        return "simple_fact"
    if lightweight_intent == "practice_generation":
        return "question_generation"
    if _has_meta_signal(question):
        return "meta"
    if any(term in question for term in ("出题", "练习题", "刷题", "生成题目", "测验")):
        return "question_generation"
    if any(term in question for term in ("批改", "判一下", "对不对", "看看我写的", "检查答案")):
        return "answer_review"
    if any(term in question for term in ("怎么做", "解题", "证明", "计算", "这道题", "步骤")):
        return "problem_solving"
    if any(term in question for term in ("项目", "代码", "架构", "仓库", "接口", "数据库", "报错")):
        return "project_analysis"
    if any(term in question for term in ("掌握度", "薄弱", "学习状态", "诊断", "复习计划", "哪里不会")):
        return "learning_diagnosis"
    if question.strip() in {"你好", "谢谢", "help", "hi", "hello"} or any(term in normalized for term in ("hello", "thanks")):
        return "smalltalk"
    if _infer_question_type(question) == "concept":
        return "concept_explain"
    return "unknown"


def _qa_scoped_intent(intent: str) -> str:
    if intent in {"question_generation", "learning_diagnosis"}:
        return "unknown"
    return intent


def _looks_like_408_scope(question: str) -> bool:
    normalized = question.lower()
    if _has_meta_signal(question) or _has_external_search_signal(question):
        return True
    terms = (
        "408",
        "数据结构",
        "算法",
        "递归",
        "动态规划",
        "线性表",
        "链表",
        "栈",
        "队列",
        "树",
        "二叉树",
        "图",
        "排序",
        "查找",
        "计算机网络",
        "网络",
        "tcp",
        "udp",
        "ip",
        "http",
        "dns",
        "路由",
        "拥塞",
        "计算机组成",
        "组成原理",
        "cpu",
        "指令",
        "Cache".lower(),
        "缓存",
        "存储器",
        "操作系统",
        "进程",
        "线程",
        "内存",
        "虚拟内存",
        "文件系统",
        "死锁",
        "调度",
    )
    return any(term in question or term in normalized for term in terms)


def _question_type_from_intent(intent: str, question: str) -> str:
    if intent == "meta":
        return "meta"
    if intent == "simple_fact":
        return "simple_fact"
    if intent == "concept_explain":
        return "concept"
    if intent == "question_generation":
        return "practice_generation"
    if intent == "answer_review":
        return "review"
    if intent in {"problem_solving", "project_analysis"}:
        return "problem"
    if intent == "learning_diagnosis":
        return "diagnosis"
    if intent == "smalltalk":
        return "smalltalk"
    return _infer_question_type(question)


def _intent_confidence(intent: str) -> float:
    return 0.82 if intent != "unknown" else 0.45


def _intent_reason(intent: str) -> str:
    reasons = {
        "meta": "meta_question_signal",
        "concept_explain": "concept_explanation_signal",
        "question_generation": "practice_generation_signal",
        "answer_review": "answer_review_signal",
        "problem_solving": "problem_solving_signal",
        "project_analysis": "project_analysis_signal",
        "learning_diagnosis": "learning_diagnosis_signal",
        "smalltalk": "smalltalk_signal",
        "simple_fact": "simple_fact_signal",
    }
    return reasons.get(intent, "no_strong_intent_signal")


def _has_meta_signal(question: str) -> bool:
    boundary = classify_question_boundary(question)
    if boundary.category == QUESTION_META_TOOL_USAGE:
        return True
    normalized = question.lower()
    chinese_terms = (
        "你是什么模型",
        "你用的什么模型",
        "你现在是什么模型",
        "现在用的什么模型",
        "当前模型",
        "模型版本",
        "你是谁",
        "你叫什么",
        "你能做什么",
        "介绍一下你",
    )
    english_terms = (
        "what model are you",
        "what model do you use",
        "which model are you",
        "which model do you use",
        "model are you",
        "who are you",
        "what can you do",
    )
    return any(term in question for term in chinese_terms) or any(
        term in normalized for term in english_terms
    )


def _is_context_dependent_question(question: str) -> bool:
    return bool(_context_dependency_signals(question))


def _context_dependency_signals(question: str) -> list[str]:
    signals = []
    for term in ("继续", "再来", "这个", "这个呢", "展开", "再详细", "刚才", "上面", "它", "这个概念"):
        if term in question:
            signals.append(term)
    return signals


def _active_topic(state: QAGraphState) -> str:
    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    for container in (session_memory, memory):
        active_topic = str(container.get("active_topic") or "").strip()
        if active_topic:
            return active_topic
        recent_topics = container.get("recent_topics")
        if isinstance(recent_topics, list) and recent_topics:
            topic = str(recent_topics[0] or "").strip()
            if topic:
                return topic
    for message in reversed(list(state.get("messages") or [])):
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if content and content != _normalized_question(state):
            return content[:80]
    return ""


def _has_strict_notebook_signal(question: str) -> bool:
    lowered = question.lower()
    strict_terms = ("只根据", "仅根据", "严格根据", "不要用通用知识", "不要联网", "only use")
    notebook_terms = ("notebook", "笔记", "资料", "文档", "pdf", "课件", "课程")
    return any(term in question or term in lowered for term in strict_terms) and any(
        term in question or term in lowered for term in notebook_terms
    )


def _has_notebook_signal(question: str) -> bool:
    lowered = question.lower()
    return any(
        term in question or term in lowered
        for term in ("根据", "依据", "基于", "当前 pdf", "当前文档", "notebook", "笔记", "资料", "课件", "课程", "知识库")
    )


def _has_external_search_signal(question: str) -> bool:
    boundary = classify_question_boundary(question)
    if boundary.category == QUESTION_META_TOOL_USAGE:
        return False
    if boundary.category == QUESTION_REALTIME_OR_FRESH:
        return True
    lowered = question.lower()
    strong_terms = (
        "调用工具",
        "用工具",
        "工具查",
        "联网",
        "联网查",
        "联网搜索",
        "网络搜索",
        "网络检索",
        "外部搜索",
        "外部检索",
        "网上查",
        "网上搜",
        "搜索",
        "搜索一下",
        "搜一下",
        "查一下",
        "查找",
        "找一下",
        "最新",
        "现在",
        "今天",
        "官网",
        "官方",
        "官方文档",
        "浏览器支持",
        "价格",
        "政策",
        "网页",
        "mdn",
        "2025",
        "2026",
        "use tool",
        "tool",
        "web search",
        "search",
        "latest",
        "current",
        "browser support",
    )
    if any(term in question or term in lowered for term in strong_terms):
        return True

    ambiguous_terms = ("检索", "找资料", "来源", "资料来源", "引用", "参考资料", "文档")
    if not any(term in question or term in lowered for term in ambiguous_terms):
        return False

    external_context_terms = (
        "网络",
        "网上",
        "网页",
        "互联网",
        "外部",
        "官网",
        "官方",
        "mdn",
        "google",
        "百度",
        "搜索",
        "最新",
        "浏览器支持",
    )
    if any(term in question or term in lowered for term in external_context_terms):
        return True

    source_terms = ("来源", "资料来源", "引用", "参考资料")
    return any(term in question or term in lowered for term in source_terms) and not _has_notebook_signal(question)


def _is_low_quality_web_source(evidence: EvidenceChunk) -> bool:
    source = f"{evidence.source_id} {evidence.metadata.get('url', '')} {evidence.metadata.get('source', '')}".lower()
    low_quality_markers = ("zhihu.com", "csdn.net", "blog.csdn", "tieba", "baijiahao", "weibo.com")
    return any(marker in source for marker in low_quality_markers)


def _hard_fallback_reason(state: QAGraphState) -> str:
    quality = dict(state.get("quality_check") or state.get("answer_quality") or {})
    external_gate = dict(state.get("external_evidence_gate") or {})
    gate = dict(state.get("evidence_gate") or {})
    if quality.get("reason"):
        return str(quality.get("reason"))
    if external_gate.get("reason"):
        return str(external_gate.get("reason"))
    if gate.get("reason"):
        return str(gate.get("reason"))
    if not _can_retry_web(state):
        return "web_retry_exhausted"
    if not _can_retry_rethink(state):
        return "rethink_retry_exhausted"
    if not _can_retry_generate(state):
        return "generate_retry_exhausted"
    return "qa_flow_hard_fallback"


def _is_simple_arithmetic_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", question.strip().lower())
    if not compact:
        return False
    compact = compact.rstrip("？?")
    compact = compact.replace("等于", "=").replace("是多少", "").replace("多少", "")
    if not re.fullmatch(r"[\d+\-*/×÷().（）=]+", compact):
        return False
    return bool(re.search(r"\d", compact) and re.search(r"[+\-*/×÷]", compact))


def _web_search_empty_concepts_enabled() -> bool:
    raw = os.getenv("QA_WEB_SEARCH_EMPTY_CONCEPTS")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _evidence_confidence_thresholds() -> tuple[float, float, float]:
    threshold = _env_float("QA_EVIDENCE_CONFIDENCE_THRESHOLD", DEFAULT_EVIDENCE_CONFIDENCE_THRESHOLD)
    high = _env_float("QA_EVIDENCE_CONFIDENCE_HIGH", DEFAULT_EVIDENCE_CONFIDENCE_HIGH)
    low = _env_float("QA_EVIDENCE_CONFIDENCE_LOW", DEFAULT_EVIDENCE_CONFIDENCE_LOW)
    threshold = _clamp(threshold)
    high = max(threshold, _clamp(high))
    low = min(threshold, _clamp(low))
    return threshold, high, low


def _evidence_confidence(
    state: QAGraphState,
    *,
    question: str,
    evidence: list[EvidenceChunk],
    source_policy: str,
) -> dict[str, Any]:
    threshold, high_threshold, low_threshold = _evidence_confidence_thresholds()
    candidates = [item for item in evidence if item.text.strip()]
    if not candidates:
        return {
            "score": 0.0,
            "level": "none",
            "threshold": threshold,
            "sufficient": False,
            "reason": "no_sufficient_notebook_evidence",
            "signals": {
                "top_score": 0.0,
                "avg_top3": 0.0,
                "usable_count": 0,
                "strong_count": 0,
                "source_alignment": 0.0,
                "coverage_bonus": 0.0,
                "strong_bonus": 0.0,
            },
        }

    ordered = sorted(candidates, key=lambda item: float(item.score or 0.0), reverse=True)
    top_scores = [float(item.score or 0.0) for item in ordered[:3]]
    top_score = top_scores[0]
    avg_top3 = sum(top_scores) / len(top_scores)
    usable_count = len(candidates)
    strong_count = len([item for item in candidates if item.score >= STRONG_EVIDENCE_SCORE])
    coverage_bonus = min(usable_count, 3) / 3 * 0.12
    strong_bonus = min(strong_count, 2) / 2 * 0.10
    source_alignment = _evidence_source_alignment(state, question=question, evidence=ordered, source_policy=source_policy)
    score = _clamp(top_score * 0.55 + avg_top3 * 0.25 + coverage_bonus + strong_bonus + source_alignment)
    sufficient = score >= threshold
    if score >= high_threshold:
        level = "high"
    elif sufficient:
        level = "medium"
    elif score >= low_threshold:
        level = "low"
    else:
        level = "none"
    reason = "evidence_confidence_sufficient" if sufficient else "low_evidence_confidence"
    return {
        "score": round(score, 4),
        "level": level,
        "threshold": threshold,
        "sufficient": sufficient,
        "reason": reason,
        "signals": {
            "top_score": round(top_score, 4),
            "avg_top3": round(avg_top3, 4),
            "usable_count": usable_count,
            "strong_count": strong_count,
            "source_alignment": round(source_alignment, 4),
            "coverage_bonus": round(coverage_bonus, 4),
            "strong_bonus": round(strong_bonus, 4),
        },
    }


def _evidence_source_alignment(
    state: QAGraphState,
    *,
    question: str,
    evidence: list[EvidenceChunk],
    source_policy: str,
) -> float:
    if not evidence:
        return 0.0
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return 0.08
    concept_linking = dict(state.get("concept_linking") or {})
    concept_id = str(concept_linking.get("concept_id") or "").strip().lower()
    topic_id = str(concept_linking.get("topic_id") or "").strip().lower()
    route_subjects = {
        str(route.get("subject_id") or route.get("knowledge_base_id") or "").strip().lower()
        for route in list(state.get("knowledge_routes") or [])
        if isinstance(route, dict)
    }
    question_terms = {term.lower() for term in _query_terms(question) if len(term.strip()) >= 2}
    for item in evidence[:3]:
        metadata = {str(key).lower(): str(value).lower() for key, value in dict(item.metadata or {}).items()}
        haystack = " ".join([item.source_id.lower(), item.text[:160].lower(), *metadata.values()])
        if concept_id and concept_id in haystack:
            return 0.08
        if topic_id and topic_id in haystack:
            return 0.08
        if route_subjects and any(subject and subject in haystack for subject in route_subjects):
            return 0.08
        if question_terms and any(term in haystack for term in question_terms):
            return 0.05
    return 0.0


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _knowledge_route(
    *,
    knowledge_base_id: str,
    subject_id: str | None,
    source_reason: str,
    priority: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "knowledge_base_id": knowledge_base_id,
        "subject_id": subject_id,
        "source_reason": source_reason,
        "priority": priority,
        "metadata": dict(metadata or {}),
    }


def _route_with_metadata(route: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    merged = dict(route)
    merged["metadata"] = {
        **dict(route.get("metadata") or {}),
        **{key: value for key, value in metadata.items() if value not in {"", None}},
    }
    return merged


def _core_408_routes(state: QAGraphState | dict[str, Any]) -> list[dict[str, Any]]:
    existing = list(state.get("knowledge_routes") or [])
    canonical_existing = [
        route
        for route in existing
        if str(route.get("subject_id") or route.get("knowledge_base_id") or "") in CANONICAL_SUBJECT_IDS
    ]
    concept_linking = dict(state.get("concept_linking") or {})
    metadata = {
        "concept_id": concept_linking.get("concept_id") or "",
        "concept_name": concept_linking.get("concept_name") or "",
        "topic_id": concept_linking.get("topic_id") or "",
        "confidence": concept_linking.get("confidence") or 0.0,
        "status": concept_linking.get("status") or "",
    }
    routes: list[dict[str, Any]] = [_route_with_metadata(route, metadata) for route in canonical_existing]
    if routes:
        return _dedupe_routes(routes)[:MAX_KNOWLEDGE_ROUTES]

    linked_subject_id = str(concept_linking.get("subject_id") or "").strip()
    if linked_subject_id in CANONICAL_SUBJECT_IDS:
        return [
            _knowledge_route(
                knowledge_base_id=linked_subject_id,
                subject_id=linked_subject_id,
                source_reason="core_408_priority",
                priority=8,
                metadata=metadata,
            )
        ]

    for subject_id in (str(state.get("notebook_id") or "").strip(), str(state.get("course_id") or "").strip()):
        if subject_id in CANONICAL_SUBJECT_IDS:
            routes.append(
                _knowledge_route(
                    knowledge_base_id=subject_id,
                    subject_id=subject_id,
                    source_reason="core_408_priority",
                    priority=8,
                    metadata=metadata,
                )
            )
    if routes:
        return _dedupe_routes(routes)[:MAX_KNOWLEDGE_ROUTES]
    for index, subject_id in enumerate(CANONICAL_SUBJECT_IDS, start=1):
        routes.append(
            _knowledge_route(
                knowledge_base_id=subject_id,
                subject_id=subject_id,
                source_reason="core_408_canonical",
                priority=50 + index,
                metadata=metadata,
            )
        )
    return _dedupe_routes(routes)[:MAX_KNOWLEDGE_ROUTES]


def _available_knowledge_bases(state: QAGraphState) -> list[dict[str, Any]]:
    raw = state.get("available_knowledge_bases") or state.get("knowledge_bases") or []
    if not isinstance(raw, list):
        raw = []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            candidates.append(dict(item))
        else:
            candidates.append(
                {
                    "id": getattr(item, "id", ""),
                    "name": getattr(item, "name", ""),
                    "description": getattr(item, "description", ""),
                    "doc_count": getattr(item, "doc_count", 0),
                }
            )
    if candidates:
        return candidates
    return [{**dict(item), "canonical_default": True} for item in DEFAULT_SUBJECTS]


def _route_from_candidate(candidate: dict[str, Any], question: str) -> dict[str, Any] | None:
    candidate_id = str(candidate.get("id") or candidate.get("subject_id") or candidate.get("knowledge_base_id") or "").strip()
    if not candidate_id:
        return None
    display_values = [
        str(candidate.get(key) or "").strip()
        for key in ("name", "title", "subject_name")
        if str(candidate.get(key) or "").strip()
    ]
    if any(value and value in question for value in display_values):
        return _knowledge_route(
            knowledge_base_id=candidate_id,
            subject_id=str(candidate.get("subject_id") or candidate_id),
            source_reason="explicit_named_knowledge_base",
            priority=10,
            metadata={
                "name": candidate.get("name") or candidate.get("title") or "",
                "description": candidate.get("description") or "",
            },
        )
    if bool(candidate.get("canonical_default")):
        return None
    haystack = " ".join(
        str(candidate.get(key) or "") for key in ("name", "title", "description", "subject_name")
    ).lower()
    terms = [term.lower() for term in _query_terms(question) if len(term.strip()) >= 2]
    if not terms or not any(term in haystack for term in terms):
        return None
    return _knowledge_route(
        knowledge_base_id=candidate_id,
        subject_id=str(candidate.get("subject_id") or candidate_id),
        source_reason="topic_matched_knowledge_base",
        priority=50,
        metadata={
            "name": candidate.get("name") or candidate.get("title") or "",
            "description": candidate.get("description") or "",
        },
    )


def _should_use_current_knowledge_base(
    state: QAGraphState,
    question: str,
    source_policy: str,
) -> bool:
    _ = state
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return True
    if _has_strict_notebook_signal(question):
        return True
    if _has_notebook_signal(question):
        return True
    return False


def _should_consider_knowledge_candidates(question: str, source_policy: str) -> bool:
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return True
    if _has_strict_notebook_signal(question):
        return True
    if _has_notebook_signal(question):
        return True
    return False


def _retrieval_skipped_reason(
    state: QAGraphState,
    question: str,
    source_policy: str,
) -> str:
    intent = str((state.get("intent_result") or {}).get("intent") or "")
    question_type = str(state.get("question_type") or _infer_question_type(question))
    concept_linking = dict(state.get("concept_linking") or {})
    if concept_linking.get("status") in {"ambiguous", "unmapped"}:
        return f"concept_registry_{concept_linking.get('status')}"
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value or _has_notebook_signal(question):
        return "no_matching_knowledge_base"
    if _web_search_requested_for_state(state):
        return "client_requested_web_search"
    if intent == "concept_explain" or question_type == "concept":
        return "stable_concept_model_first"
    if _has_external_search_signal(question):
        return "external_search_retrieval_stage"
    return "no_explicit_knowledge_base_signal"


def _should_run_web_retrieval(
    state: QAGraphState,
    question: str,
    source_policy: str,
) -> bool:
    boundary = _question_boundary(state, question)
    if boundary.get("category") == QUESTION_META_TOOL_USAGE:
        return False
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return False
    if source_policy not in {
        SourcePolicy.OPEN_TOOLS.value,
        SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
    }:
        return False
    if _web_search_requested_for_state(state):
        return True
    if _has_external_search_signal(question):
        return True
    if boundary.get("category") == QUESTION_STABLE_KNOWLEDGE:
        return False
    if not _web_search_empty_concepts_enabled():
        return False

    gate = dict(state.get("evidence_gate") or {})
    question_type = str(state.get("question_type") or _infer_question_type(question))
    intent = str((state.get("intent_result") or {}).get("intent") or "")
    if (
        intent in {"smalltalk", "simple_fact"}
        or question_type in {"smalltalk", "simple_fact", "practice_generation"}
        or _is_simple_arithmetic_question(question)
    ):
        return False
    if intent in {"question_generation", "answer_review", "learning_diagnosis"}:
        return False
    web_candidate = question_type in {"concept", "qa", "fact"} or intent == "concept_explain"
    if not web_candidate:
        return False
    return not gate.get("sufficient")


def _query_terms(question: str) -> list[str]:
    cleaned = (
        question.replace("？", " ")
        .replace("?", " ")
        .replace("，", " ")
        .replace(",", " ")
        .replace("。", " ")
        .replace("：", " ")
        .replace(":", " ")
    )
    terms = [item.strip(" 「」『』()（）[]【】") for item in cleaned.split() if item.strip()]
    tech_terms = []
    for token in ("HTTP/3", "HTTP", "RAG", "TCP", "IP", "TLS", "MDN", "数据库", "递归", "索引"):
        if token.lower() in question.lower():
            tech_terms.append(token)
    return [*tech_terms, *terms]


def _dedupe_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for route in routes:
        key = str(route.get("knowledge_base_id") or route.get("subject_id") or "").strip()
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None or int(route.get("priority") or 999) < int(existing.get("priority") or 999):
            by_key[key] = route
    return sorted(by_key.values(), key=lambda item: int(item.get("priority") or 999))


def _tool_request(
    state: QAGraphState,
    *,
    capability: ToolCapability,
    question: str,
    route: dict[str, Any] | None,
    risk_level: ToolRiskLevel,
    source_policy: str,
) -> ToolExecutionRequest:
    subject_id = None
    notebook_id = state.get("notebook_id")
    if route:
        subject_id = route.get("subject_id") or route.get("knowledge_base_id")
        if not notebook_id and route.get("source_reason") in {"current_notebook", "explicit_notebook_request"}:
            notebook_id = route.get("knowledge_base_id")
    concept_linking = dict(state.get("concept_linking") or {})
    route_metadata = route.get("metadata") if isinstance(route, dict) and isinstance(route.get("metadata"), dict) else {}
    concept_id = str(route_metadata.get("concept_id") or concept_linking.get("concept_id") or "").strip()
    topic_id = str(route_metadata.get("topic_id") or concept_linking.get("topic_id") or "").strip()
    if concept_linking.get("status") != "matched":
        concept_id = ""
    tool_input = {
        "query": question,
        "notebook_id": notebook_id,
        "subject_id": subject_id or state.get("course_id"),
        "knowledge_base_id": route.get("knowledge_base_id") if route else None,
        "concept_id": concept_id or None,
        "topic_id": topic_id or None,
        "user_id": state.get("user_id"),
        "top_k": 4,
        "min_score": 0.65,
    }
    if capability == ToolCapability.WEB_SEARCH:
        tool_input = {"query": question, "max_results": 5, "user_id": state.get("user_id")}
    return ToolExecutionRequest(
        capability=capability,
        input=tool_input,
        input_summary=question,
        user_id=str(state.get("user_id") or ""),
        tenant_id=state.get("tenant_id"),
        source_policy=source_policy,
        risk_level=risk_level,
        test_mode=bool(state.get("test_mode", False)),
        runtime_context={
            "graph_type": GraphType.QA.value,
            "graph_run_id": str(state.get("run_id") or ""),
            "question": question,
            "question_type": str(state.get("question_type") or ""),
            "subject_id": subject_id or state.get("course_id"),
            "notebook_id": notebook_id,
            "concept_id": concept_id or None,
            "topic_id": topic_id or None,
            "concept_linking": concept_linking,
            "knowledge_route": dict(route or {}),
            "memory": state.get("memory") or {},
            "short_term_messages": list(state.get("messages") or []),
            "session_memory": state.get("session_memory") or {},
        },
    )


def _tag_tool_result_evidence(
    result: ToolResult,
    *,
    route: dict[str, Any] | None,
    retrieval_source: str,
) -> ToolResult:
    evidence: list[EvidenceChunk] = []
    for item in result.evidence:
        metadata = {
            **dict(item.metadata),
        }
        metadata.setdefault("retrieval_source", retrieval_source)
        metadata["tool_retrieval_source"] = retrieval_source
        if route:
            metadata.update(
                {
                    "knowledge_base_id": route.get("knowledge_base_id"),
                    "subject_id": route.get("subject_id"),
                    "source_reason": route.get("source_reason"),
                }
            )
        source_type = "web" if retrieval_source == "web" else item.source_type
        evidence.append(
            item.model_copy(
                update={
                    "source_type": source_type,
                    "metadata": metadata,
                }
            )
        )
    return result.model_copy(update={"evidence": evidence})


def _tool_error_result(request: ToolExecutionRequest, exc: Exception) -> ToolResult:
    message = str(exc) or exc.__class__.__name__
    status = ToolStatus.TIMEOUT if "timeout" in message.lower() or "超时" in message else ToolStatus.ERROR
    return ToolResult(
        tool_id=f"error:{request.capability.value}",
        provider="tool_executor",
        capability=request.capability,
        status=status,
        input_summary=request.input_summary,
        output={"error_type": exc.__class__.__name__},
        error=message[:240],
    )


def _dedupe_evidence(evidence: list[EvidenceChunk]) -> list[EvidenceChunk]:
    by_id: dict[str, EvidenceChunk] = {}
    for item in evidence:
        if not item.text.strip():
            continue
        by_id[item.id] = item
    return list(by_id.values())


def _source_usage_from_evidence(evidence: list[EvidenceChunk]) -> str:
    source_types = {item.source_type for item in evidence}
    has_notebook = bool(source_types & {"notebook", "course"})
    has_web = "web" in source_types
    if has_notebook and has_web:
        return "mixed"
    if has_notebook:
        return "notebook"
    if has_web:
        return "web"
    return "model"


def _source_level_from_usage(source_usage: str, fallback: SourceLevel) -> SourceLevel:
    if source_usage == "mixed":
        return SourceLevel.MIXED
    if source_usage == "notebook":
        return SourceLevel.NOTEBOOK
    if source_usage == "web":
        return SourceLevel.WEB
    if source_usage == "model":
        if fallback == SourceLevel.NONE:
            return SourceLevel.NONE
        return SourceLevel.MODEL
    return fallback


def _collect_answer_evidence(state: QAGraphState) -> list[EvidenceChunk]:
    if state.get("evidence_judgement") or state.get("source_usage"):
        return _collect_explicit_evidence(state)
    return _collect_evidence(state)


def _collect_explicit_evidence(state: QAGraphState) -> list[EvidenceChunk]:
    return _parse_evidence_list(state.get("evidence") or [])


def _parse_evidence_list(raw_items: Any) -> list[EvidenceChunk]:
    evidence_by_id: dict[str, EvidenceChunk] = {}
    for item in list(raw_items or []):
        if isinstance(item, EvidenceChunk):
            evidence_by_id[item.id] = item
            continue
        if isinstance(item, dict):
            parsed = EvidenceChunk.model_validate(item)
            evidence_by_id[parsed.id] = parsed
    return list(evidence_by_id.values())


def _collect_evidence(state: QAGraphState) -> list[EvidenceChunk]:
    evidence_by_id: dict[str, EvidenceChunk] = {}
    for item in list(state.get("evidence") or []):
        if isinstance(item, EvidenceChunk):
            evidence_by_id[item.id] = item
            continue
        if isinstance(item, dict):
            parsed = EvidenceChunk.model_validate(item)
            evidence_by_id[parsed.id] = parsed
    for tool_result in _collect_tool_results(state):
        for item in tool_result.evidence:
            evidence_by_id[item.id] = item
    return list(evidence_by_id.values())


def _collect_tool_results(state: QAGraphState) -> list[ToolResult]:
    results: list[ToolResult] = []
    for item in list(state.get("tool_results") or []):
        if isinstance(item, ToolResult):
            results.append(item)
            continue
        if isinstance(item, dict):
            results.append(ToolResult.model_validate(item))
    return results


def _adapter_events_from_state(state: QAGraphState) -> list[LearningEvent]:
    events: list[LearningEvent] = []
    for item in list(state.get("adapter_learning_events") or []):
        if isinstance(item, LearningEvent):
            events.append(item)
            continue
        if isinstance(item, dict):
            events.append(LearningEvent.model_validate(item))
    return events


def _events_with_idempotency(events: list[LearningEvent], state: QAGraphState) -> list[LearningEvent]:
    session_id = str(state.get("thread_id") or state.get("session_id") or "")
    message_source_id = _qa_message_source_id(state)
    enriched: list[LearningEvent] = []
    for event in events:
        payload = dict(event.payload)
        payload.setdefault("session_id", session_id)
        payload.setdefault("message_id", message_source_id)
        payload.setdefault("event_type", event.event_type)
        payload.setdefault("concept_id", event.concept_id or "")
        payload.setdefault("created_at", event.created_at)
        source_object_type = str(payload.get("source_object_type") or "").strip()
        source_object_id = str(payload.get("source_object_id") or "").strip()
        if not source_object_type:
            if payload.get("evidence_id"):
                source_object_type = "evidence"
            elif payload.get("tool_result_id"):
                source_object_type = "tool_result"
            else:
                source_object_type = "chat_message"
            payload["source_object_type"] = source_object_type
        if not source_object_id:
            source_object_id = str(payload.get("evidence_id") or payload.get("tool_result_id") or message_source_id)
            payload["source_object_id"] = source_object_id
        payload.setdefault(
            "hash_key",
            learning_event_hash_key(
                event_type=event.event_type,
                user_id=event.user_id,
                concept_id=event.concept_id or "",
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                payload=payload,
            ),
        )
        enriched.append(event.model_copy(update={"payload": payload}))
    return enriched


def _emit_status(
    *,
    stream_stage: str,
    stage_label: str,
    detail: str,
    status: str = "running",
) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(
            {
                "event": "status",
                "data": {
                    "stream_stage": stream_stage,
                    "stage_label": stage_label,
                    "detail": detail,
                    "status": status,
                    "streaming_mode": "node",
                },
            }
        )
    except Exception:
        return
