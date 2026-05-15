from __future__ import annotations

from typing import Any
from uuid import uuid4

from loguru import logger

from app.domains.qa.lightweight_intent import build_lightweight_answer_schema
from app.orchestration.graphs.orchestrator.route_decider import (
    BoundaryRoute,
    RoutePolicy,
    build_current_tool_trace,
    build_route_policy,
    extract_previous_tool_trace,
)
from app.orchestration.graphs.orchestrator.schemas import (
    ChildGraphOutput,
    ChildGraphResult,
    OrchestratorIntent,
    ResponseEnvelope,
)
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import (
    FinalResponse,
    GraphError,
    GraphType,
    LearningEvent,
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


def graph_router(state: OrchestratorState) -> dict[str, Any]:
    """Route the user request to one child graph; QA-local intent stays inside QAGraph."""

    from app.orchestration.graphs.orchestrator.intent_rules import resolve_intent_decision

    return resolve_intent_decision(state)


def intent_router(state: OrchestratorState) -> dict[str, Any]:
    """Deprecated compatibility alias for graph_router."""

    return graph_router(state)


def invoke_qa_graph(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.QA).invoke(state)


def question_generation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.QUESTION_GENERATION).invoke(state)


def direct_response(state: OrchestratorState) -> dict[str, Any]:
    route_decision = state.get("route_decision") if isinstance(state.get("route_decision"), dict) else {}
    route = str(route_decision.get("route") or "")
    policy_payload = route_decision.get("policy") if isinstance(route_decision.get("policy"), dict) else {}
    policy = RoutePolicy.model_validate(policy_payload) if policy_payload else build_route_policy(state)
    trace = build_current_tool_trace(state, policy)

    if route == BoundaryRoute.SIMPLE_FACT.value:
        payload = _simple_fact_payload(state, trace=trace, route_decision=route_decision)
        status = "succeeded"
    elif route == BoundaryRoute.META_TOOL_USAGE.value:
        payload = _meta_tool_usage_payload(state, trace=trace, route_decision=route_decision)
        status = "succeeded"
    elif route == BoundaryRoute.REALTIME_OR_FRESH.value:
        payload = _realtime_without_web_payload(state, trace=trace, route_decision=route_decision)
        status = "needs_verification"
    else:
        payload = _generic_direct_payload(state, trace=trace, route_decision=route_decision)
        status = "needs_clarification"

    return _child_result_update(
        GraphType.ORCHESTRATOR,
        payload,
        status=status,
        trace_node="direct_response",
    )


def mastery_evaluation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.orchestrator.child_invokers import ChildGraphInvokerFactory

    return ChildGraphInvokerFactory.from_state(state).for_graph(GraphType.MASTERY).invoke(state)


def top_level_clarify_or_refuse(state: OrchestratorState) -> dict[str, Any]:
    """Top-level fallback for unclear intent or incomplete cross-graph requests."""

    quiz_request = state.get("quiz_request") if isinstance(state.get("quiz_request"), dict) else {}
    quiz_clarification = state.get("quiz_clarification") if isinstance(state.get("quiz_clarification"), dict) else {}
    if quiz_request and quiz_clarification:
        return _child_result_update(
            GraphType.ORCHESTRATOR,
            {
                "answer": "我可以帮你出题，但需要先确定练习方向。",
                "quiz_request": quiz_request,
                "quiz_clarification": quiz_clarification,
            },
            status="needs_clarification",
            trace_node="top_level_clarify_or_refuse",
        )

    return _child_result_update(
        GraphType.ORCHESTRATOR,
        {"answer": "我需要更明确的学习目标，才能把请求路由到合适的学习图。", "stub": True},
        status="needs_clarification",
        trace_node="top_level_clarify_or_refuse",
    )


def clarify_or_safe_response(state: OrchestratorState) -> dict[str, Any]:
    """Deprecated compatibility alias for the top-level fallback node."""

    return top_level_clarify_or_refuse(state)


def _simple_fact_payload(
    state: OrchestratorState,
    *,
    trace: dict[str, Any],
    route_decision: dict[str, Any],
) -> dict[str, Any]:
    answer_schema = build_lightweight_answer_schema(_message_text(state))
    answer = str(answer_schema.final_answer if answer_schema is not None else "").strip()
    if not answer:
        answer = "这类简单问题可以直接回答，但我没有解析出稳定结果。请换一种写法再试。"
    explanation = (
        answer_schema.model_dump(mode="json")
        if answer_schema is not None
        else {
            "topic": "简单事实",
            "thinking": answer,
            "steps": [answer],
            "mistakes": "",
            "similar": ["继续问一个简单问题", "让我帮你生成练习题"],
            "final_answer": answer,
        }
    )
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.MODEL,
        ui_payload={
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "answer_mode": BoundaryRoute.SIMPLE_FACT.value,
            "explanation": explanation,
            "tool_invocation_trace": trace,
            "route_decision": route_decision,
        },
    )
    return {
        "answer": answer,
        "final_response": response.model_dump(mode="json"),
        "tool_invocation_trace": trace,
        "route_decision": route_decision,
    }


def _meta_tool_usage_payload(
    state: OrchestratorState,
    *,
    trace: dict[str, Any],
    route_decision: dict[str, Any],
) -> dict[str, Any]:
    previous_trace = extract_previous_tool_trace(list(state.get("messages") or []))
    if previous_trace is None:
        answer = "我没有找到上一轮的工具调用记录，因此不能可靠确认刚刚是否联网搜索。"
        previous_summary: dict[str, Any] = {"trace_available": False}
    else:
        tool_count = int(previous_trace.get("toolCallCount") or 0)
        did_web = bool(previous_trace.get("didUseWebSearch"))
        did_any = bool(previous_trace.get("didUseAnyTool"))
        if did_web:
            answer = f"有。根据刚刚那轮的运行记录，工具调用次数是 {tool_count}，其中包含联网搜索。"
        elif tool_count == 0:
            answer = "没有。根据刚刚那轮的运行记录，工具调用次数是 0，因此没有调用联网搜索。"
        elif did_any:
            answer = f"没有联网搜索。根据刚刚那轮的运行记录，工具调用次数是 {tool_count}，但没有 web_search / 联网搜索调用。"
        else:
            answer = "没有。根据刚刚那轮的运行记录，没有发现联网搜索调用。"
        previous_summary = {"trace_available": True, **previous_trace}
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        ui_payload={
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "answer_mode": BoundaryRoute.META_TOOL_USAGE.value,
            "tool_invocation_trace": trace,
            "previous_tool_invocation_trace": previous_summary,
            "route_decision": route_decision,
        },
    )
    return {
        "answer": answer,
        "final_response": response.model_dump(mode="json"),
        "tool_invocation_trace": trace,
        "previous_tool_invocation_trace": previous_summary,
        "route_decision": route_decision,
    }


def _realtime_without_web_payload(
    state: OrchestratorState,
    *,
    trace: dict[str, Any],
    route_decision: dict[str, Any],
) -> dict[str, Any]:
    boundary = route_decision.get("boundary") if isinstance(route_decision.get("boundary"), dict) else {}
    question = _message_text(state)
    if boundary.get("contains_relative_year") and trace.get("currentDate") is None:
        answer = (
            "这是实时问题，但我无法确定你说的“今年”是哪一年；请补充年份，"
            "或启用联网检索后我再核查官方来源。"
        )
    else:
        if not trace.get("hasWebSearchTool") or not trace.get("webSearchEnabled"):
            availability = "我当前没有启用联网检索"
        else:
            availability = "本轮没有取得联网检索结果"
        topic = (
            "今年 GPT/ChatGPT/OpenAI 模型发布到了哪个版本"
            if any(token in question.lower() for token in ("gpt", "openai", "chatgpt", "api", "模型"))
            else "这个当前状态"
        )
        answer = (
            f"这是实时问题，{availability}，不能可靠确认{topic}。"
            "若只基于我的知识截止时间，我不能把它当作当前事实。"
            "需要联网核查官方发布页、官方文档或权威来源后，才能给出确定答案。"
        )
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        ui_payload={
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "answer_mode": "realtime_requires_web",
            "question_boundary": boundary,
            "tool_invocation_trace": trace,
            "route_decision": route_decision,
            "volatile_fact": True,
        },
    )
    return {
        "answer": answer,
        "final_response": response.model_dump(mode="json"),
        "tool_invocation_trace": trace,
        "route_decision": route_decision,
    }


def _generic_direct_payload(
    state: OrchestratorState,
    *,
    trace: dict[str, Any],
    route_decision: dict[str, Any],
) -> dict[str, Any]:
    answer = "我需要更明确的学习目标，才能把请求路由到合适的学习图。"
    response = FinalResponse(
        answer=answer,
        source_level=SourceLevel.NONE,
        ui_payload={
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "answer_mode": "direct_fallback",
            "tool_invocation_trace": trace,
            "route_decision": route_decision,
        },
    )
    return {
        "answer": answer,
        "final_response": response.model_dump(mode="json"),
        "tool_invocation_trace": trace,
        "route_decision": route_decision,
    }


def _child_result_update(
    graph_type: GraphType,
    payload: dict[str, Any],
    *,
    status: str,
    trace_node: str,
) -> dict[str, Any]:
    output = ChildGraphOutput(target_graph_type=graph_type, payload=payload)
    result = ChildGraphResult(
        task_type=graph_type.value,
        status=status,
        content=payload,
        learning_events=[item for item in list(payload.get("learning_events") or []) if isinstance(item, dict)],
        audit_event={
            "graph_type": graph_type.value,
            "status": status,
            "node": trace_node,
        },
        ui_payload=payload.get("ui_payload") if isinstance(payload.get("ui_payload"), dict) else {},
        trace_steps=[{"node": trace_node, "status": status, "graph_type": graph_type.value}],
        error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
    )
    return {
        "child_graph_result": result.model_dump(mode="json"),
        "child_graph_output": output.model_dump(mode="json"),
    }


def _child_graph_result_from_state(state: OrchestratorState) -> dict[str, Any]:
    result = state.get("child_graph_result") if isinstance(state.get("child_graph_result"), dict) else {}
    if result:
        return result
    output = state.get("child_graph_output") if isinstance(state.get("child_graph_output"), dict) else {}
    payload = output.get("payload") if isinstance(output.get("payload"), dict) else {}
    task_type = str(output.get("target_graph_type") or GraphType.ORCHESTRATOR.value)
    final_response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else {}
    errors = [item for item in list(payload.get("errors") or []) if isinstance(item, dict)]
    answer = str(final_response.get("answer") or payload.get("answer") or "").strip()
    status = "failed" if errors and not answer else "degraded" if errors else "succeeded"
    return ChildGraphResult(
        task_type=task_type,
        status=status,
        content=payload,
        learning_events=[item for item in list(payload.get("learning_events") or []) if isinstance(item, dict)],
        audit_event={"graph_type": task_type, "status": status, "compat_source": "child_graph_output"},
        ui_payload=final_response.get("ui_payload") if isinstance(final_response.get("ui_payload"), dict) else {},
        trace_steps=[],
        error=errors[0] if errors and not answer else None,
    ).model_dump(mode="json")


def _child_payload(state: OrchestratorState) -> dict[str, Any]:
    child_result = state.get("child_graph_result") if isinstance(state.get("child_graph_result"), dict) else {}
    content = child_result.get("content") if isinstance(child_result.get("content"), dict) else {}
    if content:
        return content
    child_output = state.get("child_graph_output") if isinstance(state.get("child_graph_output"), dict) else {}
    return child_output.get("payload") if isinstance(child_output.get("payload"), dict) else {}


def _response_envelope(
    state: OrchestratorState,
    *,
    response: FinalResponse,
    child_result: dict[str, Any],
    child_output: dict[str, Any],
    payload: dict[str, Any],
) -> ResponseEnvelope:
    response_ui = response.ui_payload if isinstance(response.ui_payload, dict) else {}
    explanation = response_ui.get("explanation") if isinstance(response_ui.get("explanation"), dict) else {}
    if not explanation:
        explanation = {
            "topic": str(response_ui.get("topic") or state.get("user_message") or ""),
            "thinking": response.answer,
            "steps": [],
            "mistakes": "",
            "similar": [item.name for item in response.concepts[1:3]],
        }
    quiz_request = (
        payload.get("quiz_request")
        if isinstance(payload.get("quiz_request"), dict)
        else state.get("quiz_request")
        if isinstance(state.get("quiz_request"), dict)
        else {}
    )
    quiz_clarification = (
        payload.get("quiz_clarification")
        if isinstance(payload.get("quiz_clarification"), dict)
        else state.get("quiz_clarification")
        if isinstance(state.get("quiz_clarification"), dict)
        else {}
    )
    quiz_items = list(payload.get("quiz_items") or payload.get("question_items") or [])
    quiz_generation_status = payload.get("quiz_generation_status")
    if not isinstance(quiz_generation_status, dict):
        quiz_generation_status = (
            payload.get("generation_status") if isinstance(payload.get("generation_status"), dict) else {}
        )
    memory = response_ui.get("memory") if isinstance(response_ui.get("memory"), dict) else {}
    final = {
        "final_answer": response.answer,
        "source_level": response.source_level.value,
        "target_graph_type": str(child_result.get("task_type") or child_output.get("target_graph_type") or ""),
        "status": str(child_result.get("status") or "succeeded"),
    }
    sync_payload = {
        "question_type": _question_type_for_envelope(state),
        "route": _route_for_envelope(state, response),
        "explanation": explanation,
        "final_answer": response.answer,
        "quiz_items": quiz_items,
        "quiz_request": quiz_request,
        "quiz_clarification": quiz_clarification,
        "quiz_generation_status": quiz_generation_status,
        "memory": memory,
    }
    sse_events = [
        {"event": "explanation", "data": {"explanation": explanation, "final_answer": response.answer}},
        {"event": "final", "data": final},
    ]
    if quiz_items or quiz_clarification:
        sse_events.insert(
            1,
            {
                "event": "quiz",
                "data": {
                    "items": quiz_items,
                    "quiz_request": quiz_request,
                    "quiz_clarification": quiz_clarification,
                    "quiz_generation_status": quiz_generation_status,
                },
            },
        )
    return ResponseEnvelope(
        explanation=explanation,
        quiz={
            "items": quiz_items,
            "quiz_request": quiz_request,
            "quiz_clarification": quiz_clarification,
            "quiz_generation_status": quiz_generation_status,
        },
        memory=memory,
        final=final,
        sse_events=sse_events,
        sync_payload=sync_payload,
    )


def _question_type_for_envelope(state: OrchestratorState) -> str:
    intent = str((state.get("intent_decision") or {}).get("intent") or OrchestratorIntent.QA.value)
    route = str((state.get("route_decision") or {}).get("route") or "")
    if intent == OrchestratorIntent.DIRECT_RESPONSE.value:
        if route == BoundaryRoute.SIMPLE_FACT.value:
            return "simple_fact"
        if route == BoundaryRoute.META_TOOL_USAGE.value:
            return "meta"
        if route == BoundaryRoute.REALTIME_OR_FRESH.value:
            return "realtime_or_fresh"
        return "direct"
    if intent == OrchestratorIntent.GENERATE_QUESTION.value:
        return "practice"
    if intent == OrchestratorIntent.EVALUATE_MASTERY.value:
        return "review"
    if intent == OrchestratorIntent.FALLBACK.value:
        return "meta"
    return str(state.get("question_type") or "concept")


def _route_for_envelope(state: OrchestratorState, response: FinalResponse) -> str:
    intent = str((state.get("intent_decision") or {}).get("intent") or OrchestratorIntent.QA.value)
    if intent == OrchestratorIntent.DIRECT_RESPONSE.value:
        return "direct"
    if intent == OrchestratorIntent.GENERATE_QUESTION.value:
        return "practice"
    if response.source_level == SourceLevel.WEB:
        return "agent"
    if response.source_level == SourceLevel.NOTEBOOK:
        return "rag"
    return "explain"


def response_composer(state: OrchestratorState) -> dict[str, Any]:
    child_result = _child_graph_result_from_state(state)
    child_output = state.get("child_graph_output") if isinstance(state.get("child_graph_output"), dict) else {}
    payload = _child_payload(state)
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
                "route_decision": state.get("route_decision") or {},
                "quiz_request": state.get("quiz_request") or {},
                "quiz_clarification": state.get("quiz_clarification") or {},
                "child_graph_result": child_result,
                "child_graph_output": child_output,
            }
        }
    )
    envelope = _response_envelope(
        state,
        response=response,
        child_result=child_result,
        child_output=child_output,
        payload=payload,
    )
    return {
        "final_response": response.model_dump(mode="json"),
        "response_envelope": envelope.model_dump(mode="json"),
    }


def persist_learning_events(
    state: OrchestratorState,
    *,
    learning_event_repository: Any | None = None,
) -> dict[str, Any]:
    """Persist child graph learning events at the Orchestrator boundary."""

    child_result = _child_graph_result_from_state(state)
    payload = _child_payload(state)
    raw_events = list(child_result.get("learning_events") or payload.get("learning_events") or [])
    status = {
        "attempted": learning_event_repository is not None,
        "event_count": len(raw_events),
        "persisted_count": 0,
        "failed_open": False,
    }
    if learning_event_repository is None or not raw_events:
        return {"learning_event_persist_status": status}

    persisted_ids: list[str] = []
    errors = list(state.get("errors") or [])
    try:
        for raw_event in raw_events:
            persisted_ids.append(learning_event_repository.append(LearningEvent.model_validate(raw_event)))
    except Exception as exc:  # noqa: BLE001 - learning telemetry must never block chat answers
        error_type = exc.__class__.__name__
        logger.warning(f"Orchestrator learning event persistence failed open: {error_type}")
        status = {
            **status,
            "persisted_count": len(persisted_ids),
            "failed_open": True,
            "error_type": error_type,
        }
        errors.append(
            GraphError(
                code="orchestrator_learning_event_persist_unavailable",
                message="学习事件暂时无法持久化，已继续完成本轮问答。",
                node="persist_learning_events",
                severity="warning",
                metadata={"error_type": error_type},
            ).model_dump(mode="json")
        )
        return {
            "persisted_learning_event_ids": persisted_ids,
            "learning_event_persist_status": status,
            "errors": errors,
        }

    status = {**status, "persisted_count": len(persisted_ids)}
    return {
        "persisted_learning_event_ids": persisted_ids,
        "learning_event_persist_status": status,
    }


def persist_audit_event(state: OrchestratorState, *, audit_repository: Any | None = None) -> dict[str, Any]:
    child_result = _child_graph_result_from_state(state)
    audit_event = {
        "run_id": state.get("run_id", ""),
        "graph_run_id": state.get("run_id", ""),
        "node_name": "orchestrator.audit",
        "graph_type": GraphType.ORCHESTRATOR.value,
        "intent_decision": state.get("intent_decision") or {},
        "route_decision": state.get("route_decision") or {},
        "child_audit_event": (
            child_result.get("audit_event") if isinstance(child_result.get("audit_event"), dict) else {}
        ),
        "response_envelope_present": bool(state.get("response_envelope")),
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
