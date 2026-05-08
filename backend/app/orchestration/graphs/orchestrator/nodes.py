from __future__ import annotations

from typing import Any
from uuid import uuid4

from loguru import logger

from app.orchestration.graphs.orchestrator.schemas import ChildGraphOutput
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import (
    FinalResponse,
    GraphError,
    GraphType,
    SourceLevel,
    SourcePolicy,
)


GRAPH_VERSION = "0.1.0"


def _message_text(state: OrchestratorState) -> str:
    return str(state.get("user_message") or "").strip()


def request_guard(state: OrchestratorState) -> dict[str, Any]:
    message = _message_text(state)
    run_id = str(state.get("run_id") or uuid4())
    update: dict[str, Any] = {
        "run_id": run_id,
        "graph_type": GraphType.ORCHESTRATOR.value,
        "graph_version": str(state.get("graph_version") or GRAPH_VERSION),
        "source_policy": str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        "messages": list(state.get("messages") or []),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
    }
    if not message:
        error = GraphError(
            code="empty_user_message",
            message="用户消息不能为空。",
            node="request_guard",
        )
        update["errors"] = [*update["errors"], error.model_dump(mode="json")]
    return update


def load_runtime_context(state: OrchestratorState) -> dict[str, Any]:
    return {
        "runtime_context": {
            "available_capabilities": [
                "notebook_retrieve",
                "web_search",
                "web_extract",
                "sql_read",
                "code_execute",
                "file_parse",
            ],
            "graph_version": state.get("graph_version") or GRAPH_VERSION,
        }
    }


def load_learner_context(state: OrchestratorState) -> dict[str, Any]:
    return {
        "learner_context": {
            "user_id": state.get("user_id", ""),
            "notebook_id": state.get("notebook_id"),
            "course_id": state.get("course_id"),
            "thread_id": state.get("thread_id"),
        }
    }


def intent_router(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.intent_rules import resolve_intent_decision

    return resolve_intent_decision(state)


def qa_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.QA).invoke(state)


def question_generation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.QUESTION_GENERATION).invoke(state)


def mastery_evaluation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.MASTERY).invoke(state)


def clarify_or_safe_response(state: OrchestratorState) -> dict[str, Any]:
    quiz_request = state.get("quiz_request") if isinstance(state.get("quiz_request"), dict) else {}
    quiz_clarification = state.get("quiz_clarification") if isinstance(state.get("quiz_clarification"), dict) else {}
    if quiz_request and quiz_clarification:
        output = ChildGraphOutput(
            target_graph_type=GraphType.ORCHESTRATOR,
            payload={
                "answer": "我可以帮你出题，但需要先确定练习方向。",
                "quiz_request": quiz_request,
                "quiz_clarification": quiz_clarification,
            },
        )
        return {"child_graph_output": output.model_dump(mode="json")}

    output = ChildGraphOutput(
        target_graph_type=GraphType.ORCHESTRATOR,
        payload={"answer": "我需要更明确的学习目标，才能把请求路由到合适的学习图。", "stub": True},
    )
    return {"child_graph_output": output.model_dump(mode="json")}


def response_composer(state: OrchestratorState) -> dict[str, Any]:
    child_output = state.get("child_graph_output") if isinstance(state.get("child_graph_output"), dict) else {}
    payload = child_output.get("payload") if isinstance(child_output.get("payload"), dict) else {}
    raw_response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else payload
    if isinstance(raw_response, dict) and raw_response.get("answer"):
        response = FinalResponse.model_validate(raw_response)
    else:
        response = FinalResponse(
            answer=str(payload.get("answer") or "请求已完成路由。"),
            source_level=SourceLevel.NONE,
        )
    response = response.model_copy(
        update={
            "ui_payload": {
                **response.ui_payload,
                "intent_decision": state.get("intent_decision") or {},
                "quiz_request": state.get("quiz_request") or {},
                "quiz_clarification": state.get("quiz_clarification") or {},
                "child_graph_output": child_output,
            }
        }
    )
    return {"final_response": response.model_dump(mode="json")}


def persist_audit_event(state: OrchestratorState, *, audit_repository: Any | None = None) -> dict[str, Any]:
    audit_event = {
        "run_id": state.get("run_id", ""),
        "graph_run_id": state.get("run_id", ""),
        "node_name": "orchestrator.audit",
        "graph_type": GraphType.ORCHESTRATOR.value,
        "intent_decision": state.get("intent_decision") or {},
        "final_response_present": bool(state.get("final_response")),
    }
    errors = list(state.get("errors") or [])
    if audit_repository is not None:
        try:
            audit_repository.record_audit_event(audit_event)
        except Exception as exc:  # noqa: BLE001 - audit writes must never block user-facing graph output
            error_type = exc.__class__.__name__
            logger.warning(f"Orchestrator audit persistence failed open: {error_type}")
            audit_event = {
                **audit_event,
                "status": "degraded",
                "error_type": error_type,
            }
            errors.append(
                GraphError(
                    code="orchestrator_audit_persist_unavailable",
                    message="审计事件暂时无法持久化，已继续完成本轮请求。",
                    node="persist_audit_event",
                    severity="warning",
                    metadata={"error_type": error_type},
                ).model_dump(mode="json")
            )
    return {"audit_events": [*list(state.get("audit_events") or []), audit_event], "errors": errors}
