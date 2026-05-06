from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.orchestration.graphs.orchestrator.schemas import (
    ChildGraphOutput,
    IntentDecision,
    OrchestratorIntent,
)
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import (
    FinalResponse,
    GraphError,
    GraphType,
    SourceLevel,
    SourcePolicy,
)
from app.domains.practice.quiz_request import build_quiz_clarification_panel, resolve_quiz_request
from app.shared.schemas.contracts import QuizRequestResolution
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


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
    if state.get("errors"):
        decision = IntentDecision(
            intent=OrchestratorIntent.FALLBACK,
            confidence=1.0,
            reason="request_guard 已记录错误，进入安全响应分支。",
            target_graph_type=GraphType.ORCHESTRATOR,
        )
        return {"intent_decision": decision.model_dump(mode="json")}

    message = _message_text(state)
    lowered = message.lower()
    quiz_resolution = resolve_quiz_request(message, _quiz_context(state))
    if quiz_resolution.action == "generate_practice_pack":
        decision = IntentDecision(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.9,
            reason=quiz_resolution.reason or "命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
        )
        return {
            "intent_decision": decision.model_dump(mode="json"),
            "quiz_request": quiz_resolution.model_dump(mode="json"),
            "quiz_clarification": {},
        }
    if quiz_resolution.action == "clarify_quiz_request":
        decision = IntentDecision(
            intent=OrchestratorIntent.FALLBACK,
            confidence=0.92,
            reason=quiz_resolution.reason or "出题意图缺少练习主题，需要澄清。",
            target_graph_type=GraphType.ORCHESTRATOR,
        )
        panel = build_quiz_clarification_panel(quiz_resolution)
        return {
            "intent_decision": decision.model_dump(mode="json"),
            "quiz_request": quiz_resolution.model_dump(mode="json"),
            "quiz_clarification": panel.model_dump(mode="json"),
        }
    if any(token in message for token in ("出题", "练习题", "刷题", "生成题目")):
        decision = IntentDecision(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.82,
            reason="命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
        )
    elif any(token in message for token in ("掌握度", "评估", "评分", "薄弱", "学习状态")):
        decision = IntentDecision(
            intent=OrchestratorIntent.EVALUATE_MASTERY,
            confidence=0.88,
            reason="命中掌握度评估意图。",
            target_graph_type=GraphType.MASTERY,
        )
    elif any(token in lowered for token in ("help", "status")) or message in {"?", "？"}:
        decision = IntentDecision(
            intent=OrchestratorIntent.FALLBACK,
            confidence=0.75,
            reason="意图不完整，需要安全澄清。",
            target_graph_type=GraphType.ORCHESTRATOR,
        )
    else:
        decision = IntentDecision(
            intent=OrchestratorIntent.QA,
            confidence=0.8,
            reason="默认学习问答意图。",
            target_graph_type=GraphType.QA,
        )
    return {"intent_decision": decision.model_dump(mode="json")}


def qa_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph

    if not state.get("production_runtime"):
        result = build_qa_graph().compile().invoke(_child_state(state, GraphType.QA))
        output = ChildGraphOutput(
            target_graph_type=GraphType.QA,
            payload={
                "final_response": result.get("final_response") or {},
                "evidence": list(result.get("evidence") or []),
                "tool_results": list(result.get("tool_results") or []),
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "learning_event_count": len(result.get("learning_events") or []),
                "adapter": "qagraph",
            },
        )
        return {"child_graph_output": output.model_dump(mode="json")}

    from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL
    from app.orchestration.graphs.qa.adapter import ProductionQARuntimeAdapter
    from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
    from app.services.tooling.executor import ToolExecutor
    from app.services.tooling.policy import ToolPolicyResolver
    from app.services.tooling.registry import build_default_tool_registry

    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
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
        runtime_context={"graph_run_id": f"{state.get('run_id', '')}:{GraphType.QA.value}"},
        allow_tools=bool(runtime_context.get("allow_tools", True)),
        allow_search=bool(runtime_context.get("allow_search", True)),
    )
    event_repo = build_graph_fact_repositories().learning_events if is_graph_facts_enabled() else None
    tool_executor = ToolExecutor(
        registry=build_default_tool_registry(),
        policy_resolver=ToolPolicyResolver(),
    )
    result = build_qa_graph(
        adapter=adapter,
        learning_event_repository=event_repo,
        tool_executor=tool_executor,
    ).compile().invoke(_child_state(state, GraphType.QA))
    output = ChildGraphOutput(
        target_graph_type=GraphType.QA,
        payload={
            "final_response": result.get("final_response") or {},
            "evidence": list(result.get("evidence") or []),
            "tool_results": list(result.get("tool_results") or []),
            "learning_events": list(result.get("learning_events") or []),
            "errors": list(result.get("errors") or []),
            "learning_event_count": len(result.get("learning_events") or []),
            "adapter": "qagraph",
        },
    )
    return {"child_graph_output": output.model_dump(mode="json")}


def question_generation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    if state.get("production_runtime"):
        from app.orchestration.graphs.question_generation.graph import (
            build_production_graph as build_question_generation_graph,
        )
    else:
        from app.orchestration.graphs.question_generation.graph import build_graph as build_question_generation_graph

    result = build_question_generation_graph().compile().invoke(
        _child_state(state, GraphType.QUESTION_GENERATION)
    )
    output = ChildGraphOutput(
        target_graph_type=GraphType.QUESTION_GENERATION,
        payload={
            "final_response": result.get("final_response") or {},
            "question_items": list(result.get("question_items") or []),
            "question_item_ids": list(result.get("question_item_ids") or []),
            "learning_events": list(result.get("learning_events") or []),
            "errors": list(result.get("errors") or []),
            "quiz_request": state.get("quiz_request") or {},
            "adapter": "question_generation_graph",
        },
    )
    return {"child_graph_output": output.model_dump(mode="json")}


def mastery_evaluation_graph_stub(state: OrchestratorState) -> dict[str, Any]:
    if state.get("production_runtime"):
        from app.orchestration.graphs.mastery.graph import build_production_graph as build_mastery_graph
    else:
        from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph

    if state.get("production_runtime"):
        graph = build_mastery_graph(subject_id=str(state.get("notebook_id") or state.get("course_id") or "") or None)
    else:
        graph = build_mastery_graph()
    result = graph.compile().invoke(_child_state(state, GraphType.MASTERY))
    output = ChildGraphOutput(
        target_graph_type=GraphType.MASTERY,
        payload={
            "final_response": result.get("final_response") or {},
            "mastery_snapshot_ids": list(result.get("mastery_snapshot_ids") or []),
            "learning_events": list(result.get("learning_events") or []),
            "errors": list(result.get("errors") or []),
            "adapter": "mastery_evaluation_graph",
        },
    )
    return {"child_graph_output": output.model_dump(mode="json")}


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
    if audit_repository is not None:
        audit_repository.record_audit_event(audit_event)
    return {"audit_events": [*list(state.get("audit_events") or []), audit_event]}


def _child_state(state: OrchestratorState, graph_type: GraphType) -> dict[str, Any]:
    child_state = {
        "run_id": f"{state.get('run_id', '')}:{graph_type.value}",
        "tenant_id": state.get("tenant_id"),
        "user_id": state.get("user_id", ""),
        "notebook_id": state.get("notebook_id"),
        "course_id": state.get("course_id"),
        "thread_id": state.get("thread_id"),
        "graph_type": graph_type.value,
        "graph_version": state.get("graph_version") or GRAPH_VERSION,
        "source_policy": state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value,
        "user_message": state.get("user_message"),
        "messages": list(state.get("messages") or []),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
    }
    if graph_type == GraphType.QUESTION_GENERATION:
        quiz_request = _quiz_request(state)
        if quiz_request.is_quiz_request:
            topic = quiz_request.active_topic or quiz_request.requested_topic or quiz_request.topic or "综合练习"
            resolved_subject_id = normalize_subject_id(quiz_request.subject_id or state.get("notebook_id"))
            child_state["notebook_id"] = resolved_subject_id
            child_state["subject_id"] = resolved_subject_id
            child_state["quiz_request"] = quiz_request.model_dump(mode="json")
            child_state["user_message"] = f"围绕 {topic} 出题"
            child_state["concepts"] = [{"concept_id": _stable_concept_id(topic), "name": topic}]
            child_state["count"] = int(quiz_request.count or 5)
            child_state["requested_count"] = int(quiz_request.count or 5)
            child_state["difficulty"] = _difficulty_label(quiz_request.difficulty)
            child_state["question_type"] = "practice"
            if quiz_request.should_switch_topic:
                child_state["evidence"] = []
                child_state["tool_results"] = []
                child_state["question_candidates"] = []
                child_state["question_items"] = []
                child_state["question_item_ids"] = []
                child_state["quality_report"] = {}
                child_state["generation_status"] = {
                    "requested_count": int(quiz_request.count or 5),
                    "generated_count": 0,
                    "persisted_count": 0,
                    "retry_count": 0,
                    "topic_switched": True,
                    "previous_topic": quiz_request.previous_topic or "",
                    "active_topic": topic,
                }
    return child_state


def _quiz_context(state: OrchestratorState) -> dict[str, Any]:
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    memory = runtime_context.get("memory") if isinstance(runtime_context.get("memory"), dict) else {}
    session_memory = runtime_context.get("session_memory") if isinstance(runtime_context.get("session_memory"), dict) else {}
    context = {
        "last_topic": session_memory.get("active_topic") or memory.get("last_topic"),
        "recent_topics": list(memory.get("recent_topics") or []),
        "weak_points": list(memory.get("weak_points") or []),
        "current_question": state.get("current_question") or runtime_context.get("current_question"),
        "current_practice_question": state.get("current_practice_question") or runtime_context.get("current_practice_question"),
        "last_practice_pack": state.get("last_practice_pack") or runtime_context.get("last_practice_pack"),
        "learner_stage": runtime_context.get("learner_stage") or memory.get("learner_stage"),
        "training_mode": runtime_context.get("training_mode") or memory.get("training_mode"),
    }
    return context


def _quiz_request(state: OrchestratorState) -> QuizRequestResolution:
    if isinstance(state.get("quiz_request"), dict) and state.get("quiz_request"):
        return QuizRequestResolution.model_validate(state.get("quiz_request"))
    return resolve_quiz_request(_message_text(state), _quiz_context(state))


def _difficulty_label(difficulty: str) -> str:
    return {
        "easy": "基础",
        "medium": "变式",
        "hard": "易错",
        "adaptive": "基础",
        "unknown": "基础",
    }.get(str(difficulty or "adaptive"), "基础")


def _stable_concept_id(topic: str) -> str:
    return topic.strip().lower().replace(" ", "-")[:64] or "concept"
