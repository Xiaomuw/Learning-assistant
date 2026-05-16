from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

from app.infrastructure.llm.langsmith import trace_run
from app.orchestration.graphs.orchestrator.schemas import ChildGraphOutput, ChildGraphResult
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import (
    FinalResponse,
    GraphError,
    GraphErrorSeverity,
    GraphType,
    LearningEvent,
    LearningEventType,
    SourceLevel,
    SourcePolicy,
    build_learning_event,
)
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


class ChildGraphInvoker(Protocol):
    """Orchestrator boundary for child graph invocation.

    Invokers own trace metadata, runtime dependency wiring, state mapping, and
    wrapping child outputs back into the Orchestrator contract. Business graph
    nodes remain inside their child graph packages.
    """

    graph_type: GraphType

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        """Invoke the child graph and return an Orchestrator state update."""


@dataclass(frozen=True)
class QAGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.QA

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            try:
                result = self._invoke_production(state) if self.production_runtime else self._invoke_deterministic(state)
            except Exception as exc:  # noqa: BLE001 - child graph failures must fail open to the Orchestrator
                logger.warning(f"QAGraph invocation failed open: {exc.__class__.__name__}")
                result = _qa_child_failure_result(state, exc)
            payload = {
                "final_response": result.get("final_response") or {},
                "evidence": list(result.get("evidence") or []),
                "tool_results": list(result.get("tool_results") or []),
                "tool_calls": list(result.get("tool_calls") or []),
                "external_tool_calls": list(result.get("external_tool_calls") or []),
                "tool_invocation_trace": result.get("tool_invocation_trace") or {},
                "question_boundary": result.get("question_boundary") or {},
                "web_search_attempted": bool(result.get("web_search_attempted", False)),
                "web_search_used": bool(result.get("web_search_used", False)),
                "web_search_error": str(result.get("web_search_error") or ""),
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "runtime_summary": dict(result.get("runtime_summary") or {}),
                "learning_event_count": len(result.get("learning_events") or []),
                "adapter": "qagraph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)

    def _invoke_deterministic(self, state: OrchestratorState) -> dict[str, Any]:
        from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph

        return build_qa_graph().compile().invoke(_child_state(state, self.graph_type))

    def _invoke_production(self, state: OrchestratorState) -> dict[str, Any]:
        from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL
        from app.orchestration.graphs.qa.adapter import ProductionQARuntimeAdapter
        from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph
        from app.services.tooling.executor import ToolExecutor
        from app.services.tooling.policy import ToolPolicyResolver
        from app.services.tooling.registry import build_default_tool_registry

        runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
        requested_token_stream = bool(runtime_context.get("stream_answer_tokens"))
        injected_stream_writer = runtime_context.get("stream_writer")
        qa_runtime_context = {
            "graph_run_id": f"{state.get('run_id', '')}:{self.graph_type.value}",
            "message_id": str(state.get("message_id") or state.get("request_id") or ""),
            "request_id": str(state.get("request_id") or state.get("message_id") or ""),
            "client_request_id": str(state.get("client_request_id") or ""),
            "stream_answer_tokens": requested_token_stream,
            "sync_fast_concept_fallback": bool(runtime_context.get("sync_fast_concept_fallback", False)),
            "streaming_degraded_reason": "",
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
            "allow_web": bool(runtime_context.get("allow_web", False)),
            "web_search_requested": bool(runtime_context.get("web_search_requested") or state.get("web_search_requested")),
        }
        if qa_runtime_context["stream_answer_tokens"]:
            if callable(injected_stream_writer):
                qa_runtime_context["stream_writer"] = injected_stream_writer
            else:
                try:
                    from langgraph.config import get_stream_writer

                    qa_runtime_context["stream_writer"] = get_stream_writer()
                except Exception:
                    pass
        adapter = ProductionQARuntimeAdapter(
            model_name=str(runtime_context.get("model_name") or DEFAULT_CHAT_MODEL),
            user_id=str(runtime_context.get("user_id") or state.get("user_id") or ""),
            session_id=str(runtime_context.get("session_id") or state.get("thread_id") or ""),
            subject_id=normalize_subject_id(runtime_context.get("subject_id") or state.get("notebook_id")),
            subject_name=str(runtime_context.get("subject_name") or DEFAULT_SUBJECTS[0]["name"]),
            subject_description=str(runtime_context.get("subject_description") or ""),
            memory=dict(runtime_context.get("memory") or {}),
            short_term_messages=list(runtime_context.get("short_term_messages") or state.get("messages") or []),
            short_term_context=str(runtime_context.get("short_term_context") or ""),
            session_memory=dict(runtime_context.get("session_memory") or {}),
            session_memory_context=str(runtime_context.get("session_memory_context") or ""),
            long_term_context=str(runtime_context.get("long_term_context") or ""),
            runtime_context=qa_runtime_context,
            allow_tools=bool(runtime_context.get("allow_tools", True)),
            allow_search=bool(runtime_context.get("allow_search", True)),
        )
        tool_executor = ToolExecutor(
            registry=build_default_tool_registry(),
            policy_resolver=ToolPolicyResolver(),
        )
        return build_qa_graph(
            adapter=adapter,
            tool_executor=tool_executor,
        ).compile().invoke(_child_state(state, self.graph_type))


@dataclass(frozen=True)
class QuestionGenerationGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.QUESTION_GENERATION

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            if self.production_runtime:
                from app.orchestration.graphs.question_generation.graph import (
                    build_production_graph as build_question_generation_graph,
                )
            else:
                from app.orchestration.graphs.question_generation.graph import build_graph as build_question_generation_graph

            result = build_question_generation_graph().compile().invoke(_child_state(state, self.graph_type))
            payload = {
                "final_response": result.get("final_response") or {},
                "question_items": list(result.get("question_items") or []),
                "question_item_ids": list(result.get("question_item_ids") or []),
                "quality_report": result.get("quality_report") or {},
                "generation_status": result.get("generation_status") or {},
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "quiz_request": state.get("quiz_request") or {},
                "adapter": "question_generation_graph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)


@dataclass(frozen=True)
class MasteryEvaluationGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.MASTERY

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            if self.production_runtime:
                from app.orchestration.graphs.mastery.graph import build_production_graph as build_mastery_graph

                graph = build_mastery_graph(subject_id=str(state.get("notebook_id") or state.get("course_id") or "") or None)
            else:
                from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph

                graph = build_mastery_graph()
            result = graph.compile().invoke(_child_state(state, self.graph_type))
            payload = {
                "final_response": result.get("final_response") or {},
                "mastery_snapshots": list(result.get("mastery_snapshots") or []),
                "mastery_snapshot_ids": list(result.get("mastery_snapshot_ids") or []),
                "mastery_updates": list(result.get("mastery_updates") or []),
                "next_actions": list(result.get("next_actions") or []),
                "recommendations": list(result.get("recommendations") or []),
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "adapter": "mastery_evaluation_graph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)


class ChildGraphInvokerFactory:
    def __init__(self, *, production_runtime: bool = False) -> None:
        self.production_runtime = production_runtime

    @classmethod
    def from_state(cls, state: OrchestratorState) -> ChildGraphInvokerFactory:
        return cls(production_runtime=bool(state.get("production_runtime")))

    def for_graph(self, graph_type: GraphType) -> ChildGraphInvoker:
        invokers: dict[GraphType, ChildGraphInvoker] = {
            GraphType.QA: QAGraphInvoker(production_runtime=self.production_runtime),
            GraphType.QUESTION_GENERATION: QuestionGenerationGraphInvoker(production_runtime=self.production_runtime),
            GraphType.MASTERY: MasteryEvaluationGraphInvoker(production_runtime=self.production_runtime),
        }
        if graph_type not in invokers:
            raise ValueError(f"unsupported_child_graph_type:{graph_type.value}")
        return invokers[graph_type]


def _child_graph_update(graph_type: GraphType, payload: dict[str, Any]) -> dict[str, Any]:
    output = ChildGraphOutput(target_graph_type=graph_type, payload=payload)
    result = _child_graph_result(graph_type, payload)
    return {
        "child_graph_result": result.model_dump(mode="json"),
        "child_graph_output": output.model_dump(mode="json"),
    }


def _child_graph_result(graph_type: GraphType, payload: dict[str, Any]) -> ChildGraphResult:
    final_response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else {}
    ui_payload = final_response.get("ui_payload") if isinstance(final_response.get("ui_payload"), dict) else {}
    errors = [item for item in list(payload.get("errors") or []) if isinstance(item, dict)]
    answer = str(final_response.get("answer") or payload.get("answer") or "").strip()
    if errors and not answer:
        status = "failed"
    elif errors:
        status = "degraded"
    else:
        status = "succeeded"
    audit_event = {
        "graph_type": graph_type.value,
        "adapter": str(payload.get("adapter") or ""),
        "status": status,
        "learning_event_count": len(list(payload.get("learning_events") or [])),
        "error_count": len(errors),
    }
    trace_steps = _child_trace_steps(graph_type, payload)
    error = errors[0] if errors and not answer else None
    return ChildGraphResult(
        task_type=graph_type.value,
        status=status,
        content=payload,
        learning_events=[item for item in list(payload.get("learning_events") or []) if isinstance(item, dict)],
        audit_event=audit_event,
        ui_payload=dict(ui_payload),
        trace_steps=trace_steps,
        error=error,
    )


def _child_trace_steps(graph_type: GraphType, payload: dict[str, Any]) -> list[dict[str, Any]]:
    final_response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else {}
    response_ui = final_response.get("ui_payload") if isinstance(final_response.get("ui_payload"), dict) else {}
    runtime_summary = payload.get("runtime_summary") if isinstance(payload.get("runtime_summary"), dict) else {}
    steps: list[dict[str, Any]] = [
        {
            "node": "child_graph_invoker",
            "graph_type": graph_type.value,
            "adapter": str(payload.get("adapter") or ""),
            "status": "completed",
        }
    ]
    retrieval_report = response_ui.get("retrieval_report")
    if isinstance(retrieval_report, dict) and retrieval_report:
        steps.append({"node": "retrieval", "status": "completed", "metadata": retrieval_report})
    tool_rounds = runtime_summary.get("tool_decision_rounds")
    if isinstance(tool_rounds, list) and tool_rounds:
        steps.append(
            {
                "node": "tool_decision",
                "status": "completed",
                "metadata": {"round_count": len(tool_rounds)},
            }
        )
    return steps


def _child_trace(graph_type: GraphType, state: OrchestratorState):
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    return trace_run(
        name=f"orchestrator.child.{graph_type.value}",
        run_type="chain",
        inputs={
            "graph_type": graph_type.value,
            "user_message": state.get("user_message") or "",
            "quiz_request": state.get("quiz_request") or {},
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
            "model_name": str(runtime_context.get("model_name") or ""),
            "source_policy": str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        },
        metadata={
            "component": "ChildGraphInvoker",
            "graph_type": graph_type.value,
            "parent_run_id": str(state.get("run_id") or ""),
            "user_id": str(state.get("user_id") or ""),
            "session_id": str(state.get("thread_id") or ""),
            "subject_id": normalize_subject_id(state.get("notebook_id") or state.get("course_id")),
            "production_runtime": bool(state.get("production_runtime")),
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
            "model_name": str(runtime_context.get("model_name") or ""),
        },
        tags=["learning-assistant", "child-graph", f"graph:{graph_type.value}"],
    )


def _child_trace_outputs(graph_type: GraphType, payload: dict[str, Any]) -> dict[str, Any]:
    final_response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else {}
    response_ui = final_response.get("ui_payload") if isinstance(final_response.get("ui_payload"), dict) else {}
    runtime_summary = payload.get("runtime_summary") if isinstance(payload.get("runtime_summary"), dict) else {}
    generation_status = payload.get("generation_status") if isinstance(payload.get("generation_status"), dict) else {}
    quality_report = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    output = {
        "graph_type": graph_type.value,
        "route": _trace_route(graph_type, final_response),
        "answer": final_response.get("answer") or "",
        "safe_reasoning_summary": (
            response_ui.get("reasoning_summary")
            or runtime_summary.get("reasoning_summary")
            or ""
        ),
        "reasoning_visibility": "safe_summary_only",
        "model_name": _trace_model_name(response_ui, runtime_summary),
        "primary_model_id": str(response_ui.get("primary_model_id") or runtime_summary.get("primary_model_id") or ""),
        "fallback_model_id": str(response_ui.get("fallback_model_id") or runtime_summary.get("fallback_model_id") or ""),
        "fallback_used": bool(response_ui.get("fallback_used") or runtime_summary.get("fallback_used")),
        "fallback_reason": str(response_ui.get("fallback_reason") or runtime_summary.get("fallback_reason") or ""),
        "source_usage": str(response_ui.get("source_usage") or runtime_summary.get("source_usage") or final_response.get("source_level") or ""),
        "retrieval_diagnosis": _trace_retrieval_diagnosis(response_ui, runtime_summary),
        "retrieval_report": _trace_dict(response_ui.get("retrieval_report")),
        "tool_decision": _trace_tool_decision(payload, response_ui, runtime_summary),
        "learning_event_count": len(payload.get("learning_events") or []),
        "error_count": len(payload.get("errors") or []),
        "evidence_count": len(payload.get("evidence") or []),
        "tool_result_count": len(payload.get("tool_results") or []),
        "question_item_count": len(payload.get("question_items") or []),
        "mastery_update_count": len(payload.get("mastery_updates") or []),
        "quality_passed": quality_report.get("passed"),
        "repair_attempt_count": generation_status.get("repair_attempt_count"),
        "degraded": generation_status.get("repair_degraded") or generation_status.get("ai_generation_failed"),
    }
    return output


def _trace_route(graph_type: GraphType, final_response: dict[str, Any]) -> str:
    if graph_type == GraphType.QUESTION_GENERATION:
        return "practice"
    if graph_type == GraphType.MASTERY:
        return "review"
    source_level = str(final_response.get("source_level") or "")
    if source_level == "web":
        return "agent"
    if source_level == "notebook":
        return "rag"
    return "explain"


def _trace_model_name(response_ui: dict[str, Any], runtime_summary: dict[str, Any]) -> str:
    selected_profile = response_ui.get("selected_model_profile")
    if not isinstance(selected_profile, dict):
        selected_profile = {}
    return str(
        selected_profile.get("model_id")
        or runtime_summary.get("selected_model_id")
        or response_ui.get("primary_model_id")
        or runtime_summary.get("primary_model_id")
        or ""
    )


def _trace_retrieval_diagnosis(
    response_ui: dict[str, Any],
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    for value in (
        runtime_summary.get("retrieval_diagnosis"),
        response_ui.get("retrieval_diagnosis"),
        response_ui.get("retrieval_report"),
    ):
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _trace_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _trace_tool_decision(
    payload: dict[str, Any],
    response_ui: dict[str, Any],
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    tool_results = [item for item in list(payload.get("tool_results") or []) if isinstance(item, dict)]
    tool_decision_rounds = [
        item for item in list(runtime_summary.get("tool_decision_rounds") or []) if isinstance(item, dict)
    ]
    sanitized_rounds = [_sanitize_tool_decision_round(item) for item in tool_decision_rounds]
    capabilities = sorted(
        {
            str(item.get("capability") or item.get("tool") or "")
            for item in [*tool_results, *tool_decision_rounds]
            if str(item.get("capability") or item.get("tool") or "").strip()
        }
    )
    sources = sorted(
        {
            _public_tool_source(item)
            for item in [*tool_results, *tool_decision_rounds]
            if _public_tool_source(item)
        }
    )
    return {
        "tool_calls_count": _trace_int(runtime_summary.get("tool_calls_count") or response_ui.get("tool_calls_count")),
        "tool_decision_rounds_count": _trace_int(
            runtime_summary.get("tool_decision_rounds_count") or response_ui.get("tool_decision_rounds_count")
        ),
        "tool_decision_rounds": sanitized_rounds[:5],
        "tool_results_count": len(tool_results),
        "capabilities": capabilities,
        "sources": sources,
        "web_search_attempted": bool(response_ui.get("web_search_attempted")),
    }


def _sanitize_tool_decision_round(item: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in ("round", "decision", "tool", "capability", "status", "reason", "doc_count"):
        if key in item:
            sanitized[key] = item[key]
    source = _public_tool_source(item)
    if source:
        sanitized["source"] = source
    return sanitized


def _public_tool_source(item: dict[str, Any]) -> str:
    capability = str(item.get("capability") or item.get("tool") or item.get("name") or "").strip().lower()
    provider = str(item.get("provider") or "").strip().lower()
    if provider in {"tavily", "web"} or "web" in capability or "search" in capability:
        return "web"
    if provider == "mcp" and "web" in capability:
        return "web"
    if provider == "notebook" or "notebook" in capability:
        return "notebook"
    if provider == "internal" or provider == "runtime":
        return "tool"
    return "tool" if provider or capability else ""


def _trace_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _qa_child_failure_result(state: OrchestratorState, exc: Exception) -> dict[str, Any]:
    graph_run_id = f"{state.get('run_id', '')}:{GraphType.QA.value}"
    error_type = exc.__class__.__name__
    session_id = str(state.get("thread_id") or "")
    message_id = str(state.get("run_id") or "")
    source_object_id = f"qa_child_graph_failed:{session_id}:{message_id}"
    response = FinalResponse(
        answer="这一轮问答链路暂时不可用，我先安全停止，避免给出不可靠回答。",
        source_level=SourceLevel.NONE,
        coach_actions=["retry_qa"],
        mastery_signals={"signal_strength": "none"},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "qa_child_graph_failed",
            "error_type": error_type,
        },
    )
    event = build_learning_event(
        event_type=LearningEventType.ANSWER_REPAIRED.value,
        user_id=str(state.get("user_id") or ""),
        graph_run_id=graph_run_id,
        source_object_type="orchestrator_child_failure",
        source_object_id=source_object_id,
        payload={
            "reason": "qa_child_graph_failed",
            "error_type": error_type,
            "session_id": session_id,
            "message_id": message_id,
            "event_type": LearningEventType.ANSWER_REPAIRED.value,
            "concept_id": "",
        },
    )
    error = GraphError(
        code="qa_child_graph_failed",
        message=error_type,
        node="QAGraphInvoker",
        severity=GraphErrorSeverity.ERROR,
        metadata={"graph_type": GraphType.QA.value},
    )
    return {
        "final_response": response.model_dump(mode="json"),
        "learning_events": [event.model_dump(mode="json")],
        "errors": [error.model_dump(mode="json")],
        "runtime_summary": {"error_type": error_type, "degraded": True},
    }


def _persist_fallback_learning_events_safely(raw_events: list[Any]) -> None:
    if not raw_events:
        return
    try:
        from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled

        if not is_graph_facts_enabled():
            return
        repository = build_graph_fact_repositories().learning_events
        for raw_event in raw_events:
            repository.append(LearningEvent.model_validate(raw_event))
    except Exception as exc:  # noqa: BLE001 - fallback telemetry must never block user output
        logger.warning(f"QAGraph fallback learning event persistence failed open: {exc.__class__.__name__}")


def _child_state(state: OrchestratorState, graph_type: GraphType) -> dict[str, Any]:
    message = str(state.get("user_message") or "").strip()
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    return {
        "run_id": f"{state.get('run_id', '')}:{graph_type.value}",
        "tenant_id": state.get("tenant_id", ""),
        "user_id": state.get("user_id", ""),
        "notebook_id": state.get("notebook_id"),
        "course_id": state.get("course_id"),
        "thread_id": state.get("thread_id"),
        "message_id": str(state.get("message_id") or state.get("request_id") or ""),
        "request_id": str(state.get("request_id") or state.get("message_id") or ""),
        "client_request_id": str(state.get("client_request_id") or ""),
        "graph_type": graph_type.value,
        "graph_version": state.get("graph_version") or "0.1.0",
        "source_policy": str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        "user_message": message,
        "question": message,
        "messages": list(state.get("messages") or []),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "allow_web": bool(state.get("allow_web", False)),
        "web_search_requested": bool(state.get("web_search_requested") or runtime_context.get("web_search_requested")),
        "parent_intent_decision": state.get("intent_decision") or {},
        "quiz_request": state.get("quiz_request") or {},
        "chat_runtime_context": runtime_context,
        "production_runtime": bool(state.get("production_runtime")),
    }
