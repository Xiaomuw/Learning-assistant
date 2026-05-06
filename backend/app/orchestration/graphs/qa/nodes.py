from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.orchestration.graphs.qa.adapter import DeterministicQARuntimeAdapter, QARuntimeAdapter
from app.orchestration.graphs.qa.state import QAGraphState
from app.orchestration.graphs.shared.schemas import (
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
)
from app.persistence.interfaces import LearningEventRepository
from app.services.tooling.executor import ToolExecutor
from app.services.tooling.schemas import ToolExecutionRequest, ToolRiskLevel
from app.shared.schemas.subject import DEFAULT_SUBJECTS


GRAPH_VERSION = "0.1.0"
MIN_EVIDENCE_SCORE = 0.55
PARTIAL_EVIDENCE_SCORE = 0.55
STRONG_EVIDENCE_SCORE = 0.70
MAX_KNOWLEDGE_ROUTES = 3
MAX_WEB_REPAIRS = 1


def input_normalize_node(state: QAGraphState) -> dict[str, Any]:
    """Normalize the raw user input and initialize the v2 QA chain state."""

    question = _question(state)
    normalized_question = " ".join(question.split()).strip()
    source_policy = _source_policy({**state, "user_message": normalized_question})
    context_dependency = {
        "is_context_dependent": _is_context_dependent_question(normalized_question),
        "signals": _context_dependency_signals(normalized_question),
    }
    question_type = str(state.get("question_type") or _infer_question_type(normalized_question))
    return {
        "run_id": str(state.get("run_id") or uuid4()),
        "graph_type": GraphType.QA.value,
        "graph_version": str(state.get("graph_version") or GRAPH_VERSION),
        "source_policy": source_policy,
        "user_message": normalized_question,
        "normalized_question": normalized_question,
        "context_dependency": context_dependency,
        "messages": list(state.get("messages") or [{"role": "user", "content": normalized_question}]),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "tool_requests": list(state.get("tool_requests") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "qa_request": {
            "question": normalized_question,
            "question_type": question_type,
            "user_id": str(state.get("user_id") or ""),
            "thread_id": state.get("thread_id"),
            "notebook_id": state.get("notebook_id"),
            "course_id": state.get("course_id"),
            "source_policy": source_policy,
        },
    }


def intent_classifier_node(state: QAGraphState) -> dict[str, Any]:
    """Classify the QA request into the ChatQuestionGraph intent set."""

    question = _normalized_question(state)
    intent = _infer_intent(question)
    question_type = _question_type_from_intent(intent, question)
    qa_request = {
        **dict(state.get("qa_request") or {}),
        "question": question,
        "question_type": question_type,
    }
    return {
        "intent_result": {
            "intent": intent,
            "confidence": _intent_confidence(intent),
            "reason": _intent_reason(intent),
        },
        "question_type": question_type,
        "qa_request": qa_request,
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


def knowledge_router_node(state: QAGraphState) -> dict[str, Any]:
    """Select one or more knowledge bases before retrieval."""

    question = _resolved_question(state)
    source_policy = _source_policy(state)
    routes: list[dict[str, Any]] = []
    candidate_routes: list[dict[str, Any]] = []

    notebook_id = state.get("notebook_id")
    course_id = state.get("course_id")
    if _should_consider_knowledge_candidates(question, source_policy):
        for candidate in _available_knowledge_bases(state):
            route = _route_from_candidate(candidate, question)
            if route is not None:
                candidate_routes.append(route)

    has_named_route = any(
        str(route.get("source_reason") or "") == "explicit_named_knowledge_base"
        for route in candidate_routes
    )

    if notebook_id and _should_use_current_knowledge_base(state, question, source_policy) and not has_named_route:
        routes.append(
            _knowledge_route(
                knowledge_base_id=str(notebook_id),
                subject_id=str(notebook_id),
                source_reason="current_notebook",
                priority=20,
            )
        )
    elif (
        _should_use_current_knowledge_base(state, question, source_policy)
        and not has_named_route
    ):
        routes.append(
            _knowledge_route(
                knowledge_base_id="current_notebook",
                subject_id=None,
                source_reason="explicit_notebook_request",
                priority=30,
            )
        )

    if (
        course_id
        and str(course_id) != str(notebook_id or "")
        and _should_use_current_knowledge_base(state, question, source_policy)
        and not has_named_route
    ):
        routes.append(
            _knowledge_route(
                knowledge_base_id=str(course_id),
                subject_id=str(course_id),
                source_reason="current_course",
                priority=40,
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


def retrieval_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Retrieve notebook evidence for each selected knowledge base through capability tools."""

    routes = list(state.get("knowledge_routes") or [])
    existing_usable = [
        item for item in _collect_evidence(state) if item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    if existing_usable:
        return {
            "retrieval_report": {
                "route_count": len(routes),
                "requested_count": 0,
                "result_count": 0,
                "reason": "preloaded_evidence_available",
            }
        }
    if not routes:
        return {
            "retrieval_report": {
                "route_count": 0,
                "requested_count": 0,
                "result_count": 0,
                "reason": str(state.get("retrieval_skipped_reason") or "no_knowledge_route"),
            }
        }

    source_policy = _source_policy(state)
    question = _resolved_question(state)
    existing_requests = list(state.get("tool_requests") or [])
    existing_results = [item.model_dump(mode="json") for item in _collect_tool_results(state)]
    requests = [
        _tool_request(
            state,
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
            question=question,
            route=route,
            risk_level=ToolRiskLevel.LOW,
            source_policy=source_policy,
        )
        for route in routes
    ]
    request_payloads = [item.model_dump(mode="json") for item in requests]

    if tool_executor is None:
        return {
            "tool_requests": [*existing_requests, *request_payloads],
            "retrieval_report": {
                "route_count": len(routes),
                "requested_count": len(requests),
                "result_count": len(existing_results),
            },
        }

    new_results: list[ToolResult] = []
    for request, route in zip(requests, routes, strict=False):
        result = tool_executor.execute(request)
        new_results.append(_tag_tool_result_evidence(result, route=route, retrieval_source="notebook"))

    merged_results = [*existing_results, *[item.model_dump(mode="json") for item in new_results]]
    return {
        "tool_requests": [*existing_requests, *request_payloads],
        "tool_results": merged_results,
        "retrieval_report": {
            "route_count": len(routes),
            "requested_count": len(requests),
            "result_count": len(new_results),
            "success_count": len([item for item in new_results if item.status.value == "success"]),
        },
    }


def evidence_judge_node(state: QAGraphState) -> dict[str, Any]:
    """Judge whether retrieved knowledge-base evidence can support the answer."""

    source_policy = _source_policy(state)
    question = _resolved_question(state)
    notebook_evidence = [
        item
        for item in _collect_evidence(state)
        if item.source_type in {"notebook", "course"} and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    strong = [item for item in notebook_evidence if item.score >= STRONG_EVIDENCE_SCORE]
    if strong:
        status = "strong"
        usable = strong
        reason = "strong_notebook_evidence"
    elif notebook_evidence:
        status = "partial"
        usable = notebook_evidence
        reason = "partial_notebook_evidence"
    else:
        status = "insufficient"
        usable = []
        reason = "no_sufficient_notebook_evidence"

    notebook_required = source_policy == SourcePolicy.NOTEBOOK_ONLY.value or _has_strict_notebook_signal(question)
    if source_policy == SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value and _has_notebook_signal(question):
        notebook_required = True

    gate = {
        "sufficient": bool(usable),
        "insufficient": notebook_required and not usable,
        "source_policy": source_policy,
        "notebook_required": notebook_required,
        "usable_evidence_refs": [item.id for item in usable],
        "usable_evidence_count": len(usable),
        "missing_topic": question,
        "reason": reason,
        "status": status,
    }
    judgement = {
        "status": status,
        "missing_reason": "" if usable else reason,
        "verified_count": len(usable),
        "discarded_count": max(0, len(_collect_evidence(state)) - len(usable)),
        "strong_count": len(strong),
        "partial_count": len(notebook_evidence) - len(strong),
        "route_count": len(state.get("knowledge_routes") or []),
    }
    return {
        "evidence": [item.model_dump(mode="json") for item in usable],
        "notebook_evidence": [item.model_dump(mode="json") for item in usable],
        "evidence_judgement": judgement,
        "evidence_gate": gate,
        "grounding_report": gate,
    }


def answer_generate_node(
    state: QAGraphState,
    *,
    adapter: QARuntimeAdapter | None = None,
) -> dict[str, Any]:
    return run_adapter(state, adapter=adapter)


def answer_quality_check_node(state: QAGraphState) -> dict[str, Any]:
    """Check answer quality and decide whether web fallback is needed."""

    source_policy = _source_policy(state)
    final_response = FinalResponse.model_validate(state.get("final_response") or {})
    question = _resolved_question(state)
    evidence = _collect_evidence(state)
    evidence_by_id = {item.id: item for item in evidence}
    web_used = any(item.source_type == "web" for item in evidence)
    notebook_used = any(item.source_type in {"notebook", "course"} for item in evidence)
    issues: list[str] = []
    needs_web = False

    if not final_response.answer.strip():
        issues.append("empty_answer")
    if final_response.evidence_refs and any(ref not in evidence_by_id for ref in final_response.evidence_refs):
        issues.append("evidence_ref_missing")
    if _has_external_search_signal(question) and not web_used and source_policy != SourcePolicy.NOTEBOOK_ONLY.value:
        issues.append("time_sensitive_without_web")
        needs_web = True
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value and final_response.source_level == SourceLevel.NOTEBOOK and not notebook_used:
        issues.append("notebook_claim_without_evidence")

    status = "pass"
    if issues:
        status = "needs_web_search" if needs_web else "failed"
    return {
        "answer_quality": {
            "status": status,
            "issues": issues,
            "needs_web_search": needs_web,
            "reason": issues[0] if issues else "quality_pass",
            "web_repair_count": int(state.get("web_search_iteration") or 0),
        }
    }


def should_run_web_search(state: QAGraphState) -> str:
    quality = dict(state.get("answer_quality") or {})
    if not quality.get("needs_web_search"):
        return "evidence_merge"
    if _source_policy(state) == SourcePolicy.NOTEBOOK_ONLY.value:
        return "evidence_merge"
    if bool(state.get("web_search_attempted")):
        return "evidence_merge"
    if int(state.get("web_search_iteration") or 0) >= MAX_WEB_REPAIRS:
        return "evidence_merge"
    return "web_search"


def web_search_node(
    state: QAGraphState,
    *,
    tool_executor: ToolExecutor | None = None,
) -> dict[str, Any]:
    """Run web search as a post-answer quality fallback when policy allows it."""

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
    """Merge notebook and web evidence while keeping source classes explicit."""

    all_evidence = _collect_evidence(state)
    notebook = [
        item
        for item in all_evidence
        if item.source_type in {"notebook", "course"} and item.text.strip() and item.score >= PARTIAL_EVIDENCE_SCORE
    ]
    web = [item for item in all_evidence if item.source_type == "web" and item.text.strip()]
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


def final_response_node(state: QAGraphState) -> dict[str, Any]:
    """Compose the final contract response with v2 QA process metadata."""

    response = FinalResponse.model_validate(state.get("final_response") or {})
    evidence = _collect_evidence(state)
    source_usage = str(state.get("source_usage") or _source_usage_from_evidence(evidence))
    source_level = _source_level_from_usage(source_usage, response.source_level)
    evidence_refs = [item.id for item in evidence] if evidence else list(response.evidence_refs)
    answer = response.answer

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

    ui_payload = {
        **dict(response.ui_payload),
        "chat_question_graph_version": "v2",
        "intent_result": dict(state.get("intent_result") or {}),
        "knowledge_routes": list(state.get("knowledge_routes") or []),
        "retrieval_skipped_reason": str(state.get("retrieval_skipped_reason") or ""),
        "retrieval_report": dict(state.get("retrieval_report") or {}),
        "evidence_judgement": dict(state.get("evidence_judgement") or {}),
        "answer_quality": dict(state.get("answer_quality") or {}),
        "source_usage": source_usage,
        "web_search_attempted": bool(state.get("web_search_attempted")),
    }
    final_response = response.model_copy(
        update={
            "answer": answer,
            "source_level": source_level,
            "evidence_refs": evidence_refs,
            "ui_payload": ui_payload,
        }
    )
    return {"final_response": final_response.model_dump(mode="json"), "errors": update_errors}


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
    capabilities: list[ToolCapability] = []
    if source_policy in {SourcePolicy.NOTEBOOK_ONLY.value, SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value}:
        capabilities.append(ToolCapability.NOTEBOOK_RETRIEVE)
    elif _has_notebook_signal(question):
        capabilities.append(ToolCapability.NOTEBOOK_RETRIEVE)

    if source_policy == SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value and _has_external_search_signal(question):
        capabilities.append(ToolCapability.WEB_SEARCH)
    elif source_policy == SourcePolicy.OPEN_TOOLS.value and _has_external_search_signal(question):
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
    evidence = _collect_evidence(state)
    evidence_gate = dict(state.get("evidence_gate") or {})
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
        }
        if contract_result.evidence:
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
    return {"final_response": response.model_dump(mode="json")}


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
    tool_result_refs = [item.tool_id for item in _collect_tool_results(state)]
    base_payload = {
        "question_type": str(qa_request.get("question_type") or _infer_question_type(_question(state))),
        "source_level": response.source_level.value,
        "source_policy": source_policy,
        "answer_mode": str(response.ui_payload.get("answer_mode") or ""),
        "evidence_refs": list(response.evidence_refs),
        "tool_result_refs": tool_result_refs,
        "degraded": bool((state.get("evidence_gate") or {}).get("insufficient")),
    }
    events = _adapter_events_from_state(state)
    events.append(
        LearningEvent(
            event_type=LearningEventType.QUESTION_ANSWERED.value,
            user_id=str(state.get("user_id") or ""),
            graph_run_id=str(state.get("run_id") or ""),
            payload=base_payload,
        )
    )

    if (state.get("evidence_gate") or {}).get("insufficient"):
        events.append(
            LearningEvent(
                event_type=LearningEventType.INSUFFICIENT_EVIDENCE.value,
                user_id=str(state.get("user_id") or ""),
                graph_run_id=str(state.get("run_id") or ""),
                payload={
                    "missing_topic": _question(state),
                    "source_policy": source_policy,
                    "reason": (state.get("evidence_gate") or {}).get("reason"),
                },
            )
        )

    for concept in response.concepts:
        events.append(
            LearningEvent(
                event_type=LearningEventType.CONCEPT_EXPLAINED.value,
                user_id=str(state.get("user_id") or ""),
                concept_id=concept.concept_id,
                graph_run_id=str(state.get("run_id") or ""),
                payload={
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "confidence": concept.confidence,
                    "source_level": response.source_level.value,
                    "evidence_refs": list(response.evidence_refs),
                },
            )
        )

    evidence_by_id = {item.id: item for item in _collect_evidence(state)}
    for evidence_ref in response.evidence_refs:
        evidence = evidence_by_id.get(evidence_ref)
        if evidence is None:
            continue
        events.append(
            LearningEvent(
                event_type=LearningEventType.EVIDENCE_USED.value,
                user_id=str(state.get("user_id") or ""),
                concept_id=evidence.concepts[0].concept_id if evidence.concepts else None,
                graph_run_id=str(state.get("run_id") or ""),
                payload={
                    "evidence_id": evidence.id,
                    "source_type": evidence.source_type,
                    "score": evidence.score,
                    "grounding_status": "used",
                },
            )
        )

    for tool_result in _collect_tool_results(state):
        if tool_result.status.value != "success":
            continue
        if tool_result.capability not in {ToolCapability.NOTEBOOK_RETRIEVE, ToolCapability.WEB_SEARCH, ToolCapability.WEB_EXTRACT}:
            continue
        events.append(
            LearningEvent(
                event_type=LearningEventType.TOOL_FALLBACK_USED.value,
                user_id=str(state.get("user_id") or ""),
                graph_run_id=str(state.get("run_id") or ""),
                payload={
                    "capability": tool_result.capability.value,
                    "provider": tool_result.provider,
                    "tool_result_id": tool_result.tool_id,
                    "evidence_count": len(tool_result.evidence),
                },
            )
        )

    return {"learning_events": [item.model_dump(mode="json") for item in events]}


def persist_learning_events(
    state: QAGraphState,
    *,
    learning_event_repository: LearningEventRepository | None = None,
) -> dict[str, Any]:
    if learning_event_repository is None:
        return {}

    persisted_ids: list[str] = []
    for raw_event in list(state.get("learning_events") or []):
        event = LearningEvent.model_validate(raw_event)
        persisted_ids.append(learning_event_repository.append(event))
    return {"persisted_learning_event_ids": persisted_ids}


def _normalized_question(state: QAGraphState) -> str:
    return str(state.get("normalized_question") or _question(state)).strip()


def _resolved_question(state: QAGraphState) -> str:
    return str(state.get("resolved_question") or _normalized_question(state)).strip()


def _question(state: QAGraphState) -> str:
    return str(state.get("user_message") or state.get("question") or "").strip()


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


def _infer_question_type(question: str) -> str:
    normalized = question.lower()
    if any(token in question for token in ("什么是", "什么叫", "解释", "概念")):
        return "concept"
    if any(token in normalized for token in ("what is", "define", "explain")):
        return "concept"
    return "qa"


def _infer_intent(question: str) -> str:
    normalized = question.lower()
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


def _question_type_from_intent(intent: str, question: str) -> str:
    if intent == "concept_explain":
        return "concept"
    if intent == "question_generation":
        return "practice"
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
        "concept_explain": "concept_explanation_signal",
        "question_generation": "practice_generation_signal",
        "answer_review": "answer_review_signal",
        "problem_solving": "problem_solving_signal",
        "project_analysis": "project_analysis_signal",
        "learning_diagnosis": "learning_diagnosis_signal",
        "smalltalk": "smalltalk_signal",
    }
    return reasons.get(intent, "no_strong_intent_signal")


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
    lowered = question.lower()
    return any(
        term in question or term in lowered
        for term in (
            "最新",
            "现在",
            "当前",
            "今天",
            "官网",
            "官方",
            "文档",
            "来源",
            "引用",
            "浏览器支持",
            "价格",
            "政策",
            "搜索",
            "查一下",
            "mdn",
            "2025",
            "2026",
            "latest",
            "current",
            "browser support",
        )
    )


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
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value or _has_notebook_signal(question):
        return "no_matching_knowledge_base"
    if intent == "concept_explain" or question_type == "concept":
        return "stable_concept_model_first"
    if _has_external_search_signal(question):
        return "external_search_quality_fallback_only"
    return "no_explicit_knowledge_base_signal"


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
    tool_input = {
        "query": question,
        "notebook_id": notebook_id,
        "subject_id": subject_id or state.get("course_id"),
        "knowledge_base_id": route.get("knowledge_base_id") if route else None,
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
            "retrieval_source": retrieval_source,
        }
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
