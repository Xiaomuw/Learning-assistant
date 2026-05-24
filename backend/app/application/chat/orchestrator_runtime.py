from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from loguru import logger

from app.application.chat.answer_cleaning import (
    clean_display_answer,
    clean_display_steps,
    compose_display_answer,
    should_preserve_notebook_notice,
)
from app.application.chat.messages import normalize_explanation_payload
from app.infrastructure.llm.langsmith import trace_run
from app.orchestration.graphs.orchestrator.graph import build_graph as build_orchestrator_graph
from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
from app.shared.schemas.agent_graphs import FinalResponse, GraphType, SourcePolicy, ToolResult
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id
from app.shared.schemas.state import AgentState


def run_orchestrator_chat(
    initial_state: AgentState | dict[str, Any],
    *,
    request_mode: str,
) -> dict[str, Any]:
    """Run the production LearningOrchestratorGraph and map it to chat state."""

    state = dict(initial_state)
    graph_run_id = str(state.get("run_id") or f"orchestrator-{uuid4()}")
    repos = build_graph_fact_repositories() if is_graph_facts_enabled() else None
    t0 = time.perf_counter()
    _start_graph_run_safely(repos, state, graph_run_id, request_mode=request_mode)

    result: dict[str, Any] = {}
    error_type = ""
    try:
        with trace_run(
            name=f"chat.orchestrator.{request_mode}",
            run_type="chain",
            inputs=_trace_inputs(state, request_mode=request_mode),
            metadata={
                "component": "LearningOrchestratorGraph",
                "entry": request_mode,
                "user_id": str(state.get("user_id") or ""),
                "session_id": str(state.get("session_id") or ""),
                "subject_id": normalize_subject_id(state.get("subject_id")),
                "graph_run_id": graph_run_id,
            },
            tags=["learning-assistant", "orchestrator", f"entry:{request_mode}"],
        ) as run:
            result = build_orchestrator_graph(
                audit_repository=repos.graph_runs if repos is not None else None,
                learning_event_repository=repos.learning_events if repos is not None else None,
            ).compile().invoke(_orchestrator_state_from_chat_state(state, graph_run_id=graph_run_id))
            run.end(outputs=_trace_outputs(result))
    except Exception as exc:
        error_type = exc.__class__.__name__
        logger.exception(f"LearningOrchestratorGraph failed: {error_type}")
        result = _error_orchestrator_result(
            state,
            graph_run_id=graph_run_id,
            error_type=error_type,
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    _record_child_facts_safely(
        repos,
        state,
        result,
        graph_run_id=graph_run_id,
        request_mode=request_mode,
        latency_ms=latency_ms,
        error_type=error_type,
    )
    return _chat_state_from_orchestrator_result(
        initial_state=state,
        graph_result=result,
        request_mode=request_mode,
        latency_ms=latency_ms,
    )


def stream_orchestrator_chat(
    initial_state: AgentState | dict[str, Any],
    *,
    request_mode: str,
) -> Iterator[dict[str, Any]]:
    """Run LearningOrchestratorGraph in update-stream mode and yield chat chunks.

    This is graph-level streaming: nodes emit progress as soon as they finish.
    Token-level streaming is intentionally not claimed here because several QA
    modes use structured/tool-calling invocations that are not safely streamable.
    """

    state = dict(initial_state)
    if request_mode == "sse":
        state["stream_answer_tokens"] = True
    graph_run_id = str(state.get("run_id") or f"orchestrator-{uuid4()}")
    repos = build_graph_fact_repositories() if is_graph_facts_enabled() else None
    t0 = time.perf_counter()
    _start_graph_run_safely(repos, state, graph_run_id, request_mode=request_mode)
    graph_input = _orchestrator_state_from_chat_state(state, graph_run_id=graph_run_id)
    graph_state = dict(graph_input)
    result: dict[str, Any] = {}
    error_type = ""
    emitted_answer = False

    try:
        with trace_run(
            name=f"chat.orchestrator.{request_mode}",
            run_type="chain",
            inputs=_trace_inputs(state, request_mode=request_mode),
            metadata={
                "component": "LearningOrchestratorGraph",
                "entry": request_mode,
                "user_id": str(state.get("user_id") or ""),
                "session_id": str(state.get("session_id") or ""),
                "subject_id": normalize_subject_id(state.get("subject_id")),
                "graph_run_id": graph_run_id,
                "streaming_mode": "mixed",
            },
            tags=["learning-assistant", "orchestrator", f"entry:{request_mode}", "streaming:mixed"],
        ) as run:
            compiled = build_orchestrator_graph(
                audit_repository=repos.graph_runs if repos is not None else None,
                learning_event_repository=repos.learning_events if repos is not None else None,
            ).compile()
            for raw_update in compiled.stream(
                graph_input,
                stream_mode=["updates", "custom"],
                version="v2",
            ):
                custom_chunk = _custom_chunk_from_stream_part(
                    raw_update,
                    elapsed=time.perf_counter() - t0,
                )
                if custom_chunk is not None:
                    yield custom_chunk
                    continue

                update_payload = _updates_from_stream_part(raw_update)
                if not isinstance(update_payload, dict):
                    continue
                for node_name, node_update in update_payload.items():
                    if not isinstance(node_update, dict):
                        continue
                    graph_state.update(node_update)
                    elapsed = time.perf_counter() - t0
                    chunk = _stream_chunk_from_orchestrator_update(
                        node_name=str(node_name),
                        node_update=node_update,
                        graph_state=graph_state,
                        initial_state=state,
                        request_mode=request_mode,
                        latency_ms=int(elapsed * 1000),
                    )
                    if chunk is None:
                        continue
                    if chunk["node"] in {"qa_agent_node", "quiz_output_node", "graph_error_node"}:
                        emitted_answer = True
                        for delta_chunk in _answer_delta_chunks(chunk):
                            yield delta_chunk
                    yield chunk
            result = graph_state
            run.end(outputs=_trace_outputs(result))
    except Exception as exc:
        error_type = exc.__class__.__name__
        logger.exception(f"LearningOrchestratorGraph stream failed: {error_type}")
        result = _error_orchestrator_result(
            state,
            graph_run_id=graph_run_id,
            error_type=error_type,
        )
        final_state = _chat_state_from_orchestrator_result(
            initial_state=state,
            graph_result=result,
            request_mode=request_mode,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        yield _final_answer_chunk(final_state, node="graph_error_node", elapsed=0.0)
        emitted_answer = True

    latency_ms = int((time.perf_counter() - t0) * 1000)
    _record_child_facts_safely(
        repos,
        state,
        result,
        graph_run_id=graph_run_id,
        request_mode=request_mode,
        latency_ms=latency_ms,
        error_type=error_type,
    )
    final_state = _chat_state_from_orchestrator_result(
        initial_state=state,
        graph_result=result,
        request_mode=request_mode,
        latency_ms=latency_ms,
    )
    if not emitted_answer:
        yield _final_answer_chunk(final_state, node="qa_agent_node", elapsed=latency_ms / 1000)
    yield {
        "node": "memory_node",
        "state_update": {"memory": final_state.get("memory") or {}},
        "elapsed": latency_ms / 1000,
    }
    yield {
        "node": "finalize_node",
        "state_update": {
            "finalized": True,
            "final_response_type": "orchestrator_graph",
            "degraded": bool(final_state.get("graph_warnings")),
            "streaming_mode": "node",
            "__final_state": final_state,
        },
        "elapsed": latency_ms / 1000,
    }
    yield {
        "node": "final",
        "state_update": {
            "finalized": True,
            "final_answer": clean_display_answer(
                str(final_state.get("final_answer") or ""),
                preserve_notebook_notice=should_preserve_notebook_notice(final_state),
            ),
            "question_type": final_state.get("question_type"),
            "route": final_state.get("route"),
            "degraded": bool(final_state.get("graph_warnings")),
            "streaming_mode": str(final_state.get("streaming_mode") or "node"),
            "streaming_token_count": int(final_state.get("streaming_token_count") or 0),
            "streaming_degraded_reason": str(final_state.get("streaming_degraded_reason") or ""),
            "model_latency_ms": latency_ms,
            "__final_state": final_state,
        },
        "elapsed": latency_ms / 1000,
    }


def _orchestrator_state_from_chat_state(
    state: dict[str, Any],
    *,
    graph_run_id: str,
) -> dict[str, Any]:
    question = str(state.get("contextual_question") or state.get("question") or "")
    source_policy = _source_policy_from_chat_state(state)
    selected_subject_id = normalize_subject_id(state.get("subject_id") or state.get("selected_subject_id"))
    knowledge_base_mode = _knowledge_base_mode_from_chat_state(state)
    raw_notebook_id = normalize_subject_id(state.get("notebook_id")) if state.get("notebook_id") else ""
    bind_current_notebook = _should_bind_current_notebook_for_question(
        state,
        question=question,
        source_policy=source_policy,
    )
    notebook_id = (raw_notebook_id or selected_subject_id) if bind_current_notebook else None
    return {
        "run_id": graph_run_id,
        "user_id": str(state.get("user_id") or ""),
        "thread_id": str(state.get("session_id") or state.get("thread_id") or ""),
        "message_id": str(state.get("message_id") or state.get("request_id") or ""),
        "request_id": str(state.get("request_id") or state.get("message_id") or ""),
        "client_request_id": str(state.get("client_request_id") or ""),
        "selected_subject_id": selected_subject_id,
        "selected_subject_name": str(state.get("subject_name") or state.get("selected_subject_name") or DEFAULT_SUBJECTS[0]["name"]),
        "selected_subject_description": str(state.get("subject_description") or state.get("selected_subject_description") or ""),
        "subject_id": selected_subject_id,
        "notebook_id": notebook_id,
        "course_id": state.get("course_id"),
        "knowledge_base_mode": knowledge_base_mode,
        "auto_web_fallback": bool(state.get("auto_web_fallback", True)),
        "source_policy": source_policy,
        "user_message": question,
        "messages": list(state.get("short_term_messages") or state.get("messages") or []),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "allow_web": bool(state.get("allow_web", False)),
        "web_search_requested": bool(state.get("web_search_requested") or state.get("allow_web")),
        "chat_runtime_context": _chat_runtime_context(state),
        "production_runtime": True,
    }


def _chat_runtime_context(state: dict[str, Any]) -> dict[str, Any]:
    selected_subject_id = normalize_subject_id(state.get("subject_id") or state.get("selected_subject_id"))
    knowledge_base_mode = _knowledge_base_mode_from_chat_state(state)
    context = {
        "user_id": str(state.get("user_id") or ""),
        "session_id": str(state.get("session_id") or ""),
        "message_id": str(state.get("message_id") or state.get("request_id") or ""),
        "request_id": str(state.get("request_id") or state.get("message_id") or ""),
        "client_request_id": str(state.get("client_request_id") or ""),
        "subject_id": selected_subject_id,
        "selected_subject_id": selected_subject_id,
        "selected_subject_name": str(state.get("subject_name") or state.get("selected_subject_name") or DEFAULT_SUBJECTS[0]["name"]),
        "selected_subject_description": str(state.get("subject_description") or state.get("selected_subject_description") or ""),
        "subject_name": str(state.get("subject_name") or DEFAULT_SUBJECTS[0]["name"]),
        "subject_description": str(state.get("subject_description") or ""),
        "knowledge_base_mode": knowledge_base_mode,
        "auto_web_fallback": bool(state.get("auto_web_fallback", True)),
        "memory": dict(state.get("memory") or {}),
        "short_term_messages": list(state.get("short_term_messages") or []),
        "short_term_context": str(state.get("short_term_context") or ""),
        "session_memory": dict(state.get("session_memory") or {}),
        "session_memory_context": str(state.get("session_memory_context") or ""),
        "long_term_context": str(state.get("long_term_context") or ""),
        "model_name": str(state.get("model_name") or ""),
        "thinking_mode": bool(state.get("thinking_mode", False)),
        "allow_web": bool(state.get("allow_web", False)),
        "web_search_requested": bool(state.get("web_search_requested") or state.get("allow_web")),
        "allow_tools": _source_policy_from_chat_state(state) != SourcePolicy.NOTEBOOK_ONLY.value,
        "allow_search": _source_policy_from_chat_state(state) in {
            SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
            SourcePolicy.OPEN_TOOLS.value,
        },
        "stream_answer_tokens": bool(state.get("stream_answer_tokens")),
        "sync_fast_concept_fallback": bool(state.get("sync_fast_concept_fallback", False)),
    }
    stream_writer = state.get("stream_writer")
    if callable(stream_writer):
        context["stream_writer"] = stream_writer
    return context


def _chat_state_from_orchestrator_result(
    *,
    initial_state: dict[str, Any],
    graph_result: dict[str, Any],
    request_mode: str,
    latency_ms: int,
) -> dict[str, Any]:
    response = FinalResponse.model_validate(graph_result.get("final_response") or {})
    intent = _intent(graph_result)
    question_type = _question_type_from_intent(intent, initial_state)
    route = _route_from_response(response, intent)
    child_payload = _child_payload(graph_result)
    response_envelope = (
        graph_result.get("response_envelope") if isinstance(graph_result.get("response_envelope"), dict) else {}
    )
    envelope_sync = response_envelope.get("sync_payload") if isinstance(response_envelope.get("sync_payload"), dict) else {}
    quiz_request = (
        envelope_sync.get("quiz_request")
        if isinstance(envelope_sync.get("quiz_request"), dict)
        else _quiz_request_payload(graph_result, child_payload, response)
    )
    quiz_clarification = (
        envelope_sync.get("quiz_clarification")
        if isinstance(envelope_sync.get("quiz_clarification"), dict)
        else _quiz_clarification_payload(graph_result, child_payload, response)
    )
    response_ui = response.ui_payload if isinstance(response.ui_payload, dict) else {}
    tool_invocation_trace = (
        child_payload.get("tool_invocation_trace")
        if isinstance(child_payload.get("tool_invocation_trace"), dict)
        else response_ui.get("tool_invocation_trace")
        if isinstance(response_ui.get("tool_invocation_trace"), dict)
        else {}
    )
    tool_calls = (
        list(child_payload.get("tool_calls") or [])
        if isinstance(child_payload.get("tool_calls"), list)
        else list(response_ui.get("tool_calls") or [])
        if isinstance(response_ui.get("tool_calls"), list)
        else []
    )
    external_tool_calls = (
        list(child_payload.get("external_tool_calls") or [])
        if isinstance(child_payload.get("external_tool_calls"), list)
        else list(response_ui.get("external_tool_calls") or [])
        if isinstance(response_ui.get("external_tool_calls"), list)
        else []
    )
    question_boundary = (
        child_payload.get("question_boundary")
        if isinstance(child_payload.get("question_boundary"), dict)
        else response_ui.get("question_boundary")
        if isinstance(response_ui.get("question_boundary"), dict)
        else {}
    )
    retrieval_skipped_reason = str(response_ui.get("retrieval_skipped_reason") or "")
    reasoning_summary = str(response_ui.get("reasoning_summary") or "")
    if not reasoning_summary and retrieval_skipped_reason == "stable_concept_model_first":
        reasoning_summary = "判断为稳定概念，本轮未调用知识库或搜索，直接按教学讲解回答。"
    quiz_items = _quiz_items_from_child_payload(child_payload)
    envelope_quiz = response_envelope.get("quiz") if isinstance(response_envelope.get("quiz"), dict) else {}
    if not quiz_items and isinstance(envelope_quiz.get("items"), list):
        quiz_items = list(envelope_quiz.get("items") or [])
    raw_explanation = (
        envelope_sync.get("explanation")
        if isinstance(envelope_sync.get("explanation"), dict)
        else response_ui.get("explanation")
        if isinstance(response_ui.get("explanation"), dict)
        else {}
    )
    if raw_explanation:
        explanation = normalize_explanation_payload(raw_explanation).model_dump()
    else:
        explanation = normalize_explanation_payload(
            {
                "topic": _topic(response, initial_state),
                "thinking": response.answer,
                "steps": [],
                "mistakes": "",
                "similar": [item.name for item in response.concepts[1:3]],
            }
        ).model_dump()
    preserve_notebook_notice = should_preserve_notebook_notice(
        {
            **initial_state,
            "source_policy": str(graph_result.get("source_policy") or initial_state.get("source_policy") or ""),
            "user_message": str(initial_state.get("question") or ""),
        }
    )
    if explanation.get("final_answer"):
        explanation["final_answer"] = clean_display_answer(
            str(explanation.get("final_answer") or ""),
            preserve_notebook_notice=preserve_notebook_notice,
        )
    if explanation.get("steps") is not None:
        explanation["steps"] = clean_display_steps(
            explanation.get("steps"),
            preserve_notebook_notice=preserve_notebook_notice,
        )
    resolved_question_type = str(envelope_sync.get("question_type") or question_type)
    final_answer = compose_display_answer(
        str(envelope_sync.get("final_answer") or response.answer),
        explanation,
        question_type=resolved_question_type,
        preserve_notebook_notice=preserve_notebook_notice,
    )
    web_search_attempted = bool(
        child_payload.get("web_search_attempted", response_ui.get("web_search_attempted", False))
        or tool_invocation_trace.get("didAttemptWebSearch")
    )
    web_search_used = bool(
        child_payload.get("web_search_used", response_ui.get("web_search_used", False))
        or tool_invocation_trace.get("didUseWebSearch")
    )
    return {
        **initial_state,
        "message_id": str(initial_state.get("message_id") or initial_state.get("request_id") or ""),
        "request_id": str(initial_state.get("request_id") or initial_state.get("message_id") or ""),
        "client_request_id": str(initial_state.get("client_request_id") or ""),
        "question_type": resolved_question_type,
        "route": str(envelope_sync.get("route") or route),
        "source_policy": str(graph_result.get("source_policy") or initial_state.get("source_policy") or ""),
        "explanation": explanation,
        "final_answer": final_answer,
        "quiz_items": quiz_items,
        "quiz_request": quiz_request,
        "quiz_clarification": quiz_clarification,
        "quiz_generation_status": _quiz_generation_status_from_child_payload(
            child_payload,
            quiz_item_count=len(quiz_items),
        ),
        "memory": dict(initial_state.get("memory") or {}),
        "final_response": response.model_dump(mode="json"),
        "response_envelope": response_envelope,
        "orchestrator_result": _compact_orchestrator_result(graph_result),
        "reasoning_summary": reasoning_summary,
        "retrieval_skipped_reason": retrieval_skipped_reason,
        "execution_mode": str(response_ui.get("execution_mode") or ""),
        "degraded": bool(response_ui.get("degraded", False)),
        "source_usage": str(response_ui.get("source_usage") or response.source_level.value),
        "selected_model_profile": response_ui.get("selected_model_profile") if isinstance(response_ui.get("selected_model_profile"), dict) else {},
        "primary_model_id": str(response_ui.get("primary_model_id") or ""),
        "fallback_model_id": str(response_ui.get("fallback_model_id") or ""),
        "fallback_used": bool(response_ui.get("fallback_used", False)),
        "fallback_reason": str(response_ui.get("fallback_reason") or ""),
        "model_attempts": list(response_ui.get("model_attempts") or [])
        if isinstance(response_ui.get("model_attempts"), list)
        else [],
        "streaming_mode": str(response_ui.get("streaming_mode") or "node"),
        "streaming_token_count": int(response_ui.get("streaming_token_count") or 0),
        "streaming_degraded_reason": str(response_ui.get("streaming_degraded_reason") or ""),
        "tool_calls": tool_calls,
        "external_tool_calls": external_tool_calls,
        "tool_invocation_trace": tool_invocation_trace,
        "question_boundary": question_boundary,
        "web_search_attempted": web_search_attempted,
        "web_search_used": web_search_used,
        "web_search_error": str(child_payload.get("web_search_error", response_ui.get("web_search_error", "")) or ""),
        "graph_runtime": {
            "mode": "orchestrator",
            "graph_type": GraphType.ORCHESTRATOR.value,
            "request_mode": request_mode,
            "latency_ms": latency_ms,
            "intent": intent,
            "error_count": len(list(graph_result.get("errors") or [])),
            "learning_event_count": _learning_event_count(graph_result),
            "tool_result_count": _tool_result_count(graph_result),
        },
        "graph_warnings": [
            item.get("code", "graph_warning")
            for item in list(graph_result.get("errors") or [])
            if isinstance(item, dict)
        ],
    }


def _stream_chunk_from_orchestrator_update(
    *,
    node_name: str,
    node_update: dict[str, Any],
    graph_state: dict[str, Any],
    initial_state: dict[str, Any],
    request_mode: str,
    latency_ms: int,
) -> dict[str, Any] | None:
    elapsed = latency_ms / 1000
    status_payloads = {
        "request_guard": ("request_guard", "请求检查", "正在检查请求是否合法。"),
        "load_runtime_context": ("load_runtime_context", "运行上下文", "正在加载模型、工具和策略上下文。"),
        "load_learner_context": ("load_learner_context", "学习者上下文", "正在加载学习者会话上下文。"),
        "persist_learning_events": ("persist_learning_events", "学习事件", "正在保存本轮学习事件。"),
    }
    if node_name in status_payloads:
        stream_stage, stage_label, detail = status_payloads[node_name]
        return {
            "node": "stream_status",
            "state_update": {
                "stream_stage": stream_stage,
                "stage_label": stage_label,
                "detail": detail,
                "status": "done",
                "streaming_mode": "node",
            },
            "elapsed": elapsed,
        }
    if node_name in {"intent_router", "graph_router"}:
        intent = _intent(graph_state)
        return {
            "node": "router",
            "state_update": {
                "question_type": _question_type_from_intent(intent, initial_state),
                "route": "practice" if intent == "generate_question" else "explain",
                "source_policy": str(graph_state.get("source_policy") or ""),
                "orchestrator_result": _compact_orchestrator_result(graph_state),
                "streaming_mode": "node",
            },
            "elapsed": elapsed,
        }
    if node_name != "response_composer" or not node_update.get("final_response"):
        return None

    try:
        final_state = _chat_state_from_orchestrator_result(
            initial_state=initial_state,
            graph_result=graph_state,
            request_mode=request_mode,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.warning(f"Failed to map stream response chunk: {exc.__class__.__name__}")
        return None

    quiz_items = list(final_state.get("quiz_items") or [])
    quiz_clarification = (
        final_state.get("quiz_clarification")
        if isinstance(final_state.get("quiz_clarification"), dict)
        else None
    )
    child_payload = _child_payload(graph_state)
    if quiz_items or quiz_clarification:
        generation_status = _quiz_generation_status_from_child_payload(
            child_payload,
            quiz_item_count=len(quiz_items),
        )
        return {
            "node": "quiz_output_node",
            "state_update": {
                "question_type": final_state.get("question_type"),
                "route": final_state.get("route"),
                "quiz_items": quiz_items,
                "quiz_request": final_state.get("quiz_request"),
                "quiz_clarification": quiz_clarification,
                "final_answer": str(final_state.get("final_answer") or ""),
                "streaming_mode": "node",
                "quiz_generation_status": generation_status,
            },
            "elapsed": elapsed,
        }
    node = "graph_error_node" if final_state.get("graph_warnings") else "qa_agent_node"
    return _final_answer_chunk(final_state, node=node, elapsed=elapsed)


def _final_answer_chunk(final_state: dict[str, Any], *, node: str, elapsed: float) -> dict[str, Any]:
    runtime = final_state.get("graph_runtime") if isinstance(final_state.get("graph_runtime"), dict) else {}
    latency_ms = int(runtime.get("latency_ms") or round(elapsed * 1000))
    explanation = final_state.get("explanation") if isinstance(final_state.get("explanation"), dict) else {}
    final_answer = compose_display_answer(
        str(final_state.get("final_answer") or ""),
        explanation,
        question_type=str(final_state.get("question_type") or ""),
        preserve_notebook_notice=should_preserve_notebook_notice(final_state),
    )
    state_update = {
        "question_type": final_state.get("question_type"),
        "route": final_state.get("route"),
        "explanation": final_state.get("explanation") or {},
        "final_answer": final_answer,
        "execution_mode": str(final_state.get("execution_mode") or "orchestrator_graph"),
        "degraded": bool(final_state.get("degraded") or final_state.get("graph_warnings")),
        "reasoning_summary": _streaming_reasoning_summary(final_state),
        "source_usage": str(final_state.get("source_usage") or ""),
        "selected_model_profile": final_state.get("selected_model_profile") or {},
        "primary_model_id": str(final_state.get("primary_model_id") or ""),
        "fallback_model_id": str(final_state.get("fallback_model_id") or ""),
        "fallback_used": bool(final_state.get("fallback_used", False)),
        "fallback_reason": str(final_state.get("fallback_reason") or ""),
        "model_attempts": list(final_state.get("model_attempts") or []),
        "streaming_mode": str(final_state.get("streaming_mode") or "node"),
        "streaming_token_count": int(final_state.get("streaming_token_count") or 0),
        "streaming_degraded_reason": str(final_state.get("streaming_degraded_reason") or ""),
        "model_latency_ms": latency_ms,
        "tool_calls": list(final_state.get("tool_calls") or []),
        "external_tool_calls": list(final_state.get("external_tool_calls") or []),
        "tool_invocation_trace": final_state.get("tool_invocation_trace") or {},
        "web_search_attempted": bool(final_state.get("web_search_attempted", False)),
        "web_search_used": bool(final_state.get("web_search_used", False)),
        "web_search_error": str(final_state.get("web_search_error") or ""),
    }
    if node == "graph_error_node":
        state_update["graph_error"] = {"message": "LearningOrchestratorGraph failed"}
    return {"node": node, "state_update": state_update, "elapsed": elapsed}


def _answer_delta_chunks(answer_chunk: dict[str, Any]) -> list[dict[str, Any]]:
    state_update = answer_chunk.get("state_update") if isinstance(answer_chunk.get("state_update"), dict) else {}
    if answer_chunk.get("node") != "qa_agent_node":
        return []
    if state_update.get("streaming_mode") == "token":
        return []
    text = str(state_update.get("final_answer") or "").strip()
    if not text:
        return []
    pieces = _split_answer_for_delta(text)
    if len(pieces) <= 1:
        return []
    elapsed = float(answer_chunk.get("elapsed") or 0)
    return [
        {
            "node": "answer_delta",
            "state_update": {
                "delta": piece,
                "streaming_mode": "node",
                "is_synthetic_delta": True,
            },
            "elapsed": elapsed,
        }
        for piece in pieces
    ]


def _split_answer_for_delta(text: str) -> list[str]:
    normalized = text.strip()
    if len(normalized) <= 80:
        return []
    pieces: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if char in "。！？!?\n" and current.strip():
            pieces.append(current)
            current = ""
    if current.strip():
        pieces.append(current)
    if len(pieces) <= 1:
        return [normalized[i : i + 80] for i in range(0, len(normalized), 80)]
    return pieces


def _streaming_reasoning_summary(final_state: dict[str, Any]) -> str:
    summary = str(final_state.get("reasoning_summary") or "").strip()
    if str(final_state.get("streaming_mode") or "") == "token":
        if bool(final_state.get("thinking_mode", False)):
            suffix = "当前为实时流式：回答内容逐步展示；原始思考仅在本轮调试面板临时显示，不写入历史或 LangSmith。"
        else:
            suffix = "当前为安全实时流式：回答内容逐步展示，处理过程只展示可审计决策摘要。"
        return f"{summary}\n\n{suffix}" if summary else suffix
    if summary:
        return f"{summary}\n\n当前为节点级流式：模型/工具节点完成后立即展示结果；本路径未暴露原始思维链。"
    return "当前为节点级流式：模型/工具节点完成后立即展示结果；本路径未暴露原始思维链。"


def _updates_from_stream_part(raw_update: Any) -> dict[str, Any] | None:
    if not isinstance(raw_update, dict):
        return None
    if raw_update.get("type") == "updates":
        data = raw_update.get("data")
        return data if isinstance(data, dict) else None
    if "type" in raw_update and "data" in raw_update:
        return None
    return raw_update


def _custom_chunk_from_stream_part(raw_update: Any, *, elapsed: float) -> dict[str, Any] | None:
    if not isinstance(raw_update, dict) or raw_update.get("type") != "custom":
        return None
    data = raw_update.get("data")
    if not isinstance(data, dict):
        return None
    event_name = str(data.get("event") or "").strip()
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if event_name == "answer_delta":
        return {
            "node": "answer_delta",
            "state_update": {
                "delta": str(payload.get("delta") or ""),
                "streaming_mode": str(payload.get("streaming_mode") or "token"),
                "is_synthetic_delta": bool(payload.get("is_synthetic_delta", False)),
            },
            "elapsed": elapsed,
        }
    if event_name == "reasoning_delta":
        return {
            "node": "reasoning_delta",
            "state_update": {
                "delta": str(payload.get("delta") or ""),
                "streaming_mode": str(payload.get("streaming_mode") or "token"),
                "source": str(payload.get("source") or "deepseek_reasoning_content"),
                "ephemeral": bool(payload.get("ephemeral", True)),
            },
            "elapsed": elapsed,
        }
    if event_name == "status":
        return {
            "node": "stream_status",
            "state_update": {
                "stream_stage": str(payload.get("stream_stage") or "model_progress"),
                "stage_label": str(payload.get("stage_label") or "实时进度"),
                "detail": str(payload.get("detail") or ""),
                "safe_decision_summary": str(payload.get("safe_decision_summary") or ""),
                "status": str(payload.get("status") or "running"),
                "streaming_mode": str(payload.get("streaming_mode") or "token"),
                "reasoning_trace_char_count": int(payload.get("reasoning_trace_char_count") or 0),
            },
            "elapsed": elapsed,
        }
    return None


def _quiz_items_from_child_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_item in list(payload.get("question_items") or []):
        if not isinstance(raw_item, dict):
            continue
        answer_key = raw_item.get("answer_key") if isinstance(raw_item.get("answer_key"), dict) else {}
        source_refs = raw_item.get("source_refs") if isinstance(raw_item.get("source_refs"), list) else []
        source_types = {
            str(ref.get("source_type") or "")
            for ref in source_refs
            if isinstance(ref, dict)
        }
        source_type = "question_bank" if "question_bank" in source_types else "ai_generated"
        source_name = "QuestionGenerationGraph"
        if source_type == "question_bank":
            first_bank_ref = next(
                (ref for ref in source_refs if isinstance(ref, dict) and ref.get("source_type") == "question_bank"),
                {},
            )
            source_name = str(first_bank_ref.get("title") or first_bank_ref.get("source_id") or "题库")
        items.append(
            {
                "question_id": str(raw_item.get("id") or ""),
                "question": str(raw_item.get("stem") or ""),
                "options": list(raw_item.get("options") or []),
                "correct_option": str(answer_key.get("correct_option") or ""),
                "explanation": str(answer_key.get("explanation") or ""),
                "option_rationales": dict(answer_key.get("option_rationales") or {}),
                "knowledge_point": str(raw_item.get("primary_concept_id") or ""),
                "concept_id": str(raw_item.get("primary_concept_id") or ""),
                "concept_name": str(raw_item.get("concept_name") or raw_item.get("primary_concept_id") or ""),
                "concept_mapping_status": "matched" if raw_item.get("primary_concept_id") else "",
                "difficulty": str(raw_item.get("difficulty") or "基础"),
                "source_type": source_type,
                "source_name": source_name,
            }
        )
    return items


def _quiz_generation_status_from_child_payload(
    payload: dict[str, Any],
    *,
    quiz_item_count: int,
) -> dict[str, Any]:
    status = payload.get("generation_status") if isinstance(payload.get("generation_status"), dict) else {}
    response = payload.get("final_response") if isinstance(payload.get("final_response"), dict) else {}
    ui_payload = response.get("ui_payload") if isinstance(response.get("ui_payload"), dict) else {}
    ui_status = (
        ui_payload.get("quiz_generation_status")
        if isinstance(ui_payload.get("quiz_generation_status"), dict)
        else {}
    )
    quality_report = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    quality_failure_summary = str(ui_payload.get("quality_failure_summary") or "").strip()
    merged = {
        **status,
        **ui_status,
        "generated_count": quiz_item_count,
        "source": "LearningOrchestratorGraph",
    }
    if quality_report:
        merged["quality_report"] = quality_report
    if quality_failure_summary:
        merged["quality_failure_summary"] = quality_failure_summary
    return merged


def _quiz_request_payload(
    graph_result: dict[str, Any],
    child_payload: dict[str, Any],
    response: FinalResponse,
) -> dict[str, Any] | None:
    payload = child_payload.get("quiz_request")
    if isinstance(payload, dict) and payload:
        return payload
    payload = response.ui_payload.get("quiz_request") if isinstance(response.ui_payload, dict) else None
    if isinstance(payload, dict) and payload:
        return payload
    payload = graph_result.get("quiz_request")
    return payload if isinstance(payload, dict) and payload else None


def _quiz_clarification_payload(
    graph_result: dict[str, Any],
    child_payload: dict[str, Any],
    response: FinalResponse,
) -> dict[str, Any] | None:
    payload = child_payload.get("quiz_clarification")
    if isinstance(payload, dict) and payload:
        return payload
    payload = response.ui_payload.get("quiz_clarification") if isinstance(response.ui_payload, dict) else None
    if isinstance(payload, dict) and payload:
        return payload
    payload = graph_result.get("quiz_clarification")
    return payload if isinstance(payload, dict) and payload else None


def _start_graph_run_safely(
    repos: Any | None,
    state: dict[str, Any],
    graph_run_id: str,
    *,
    request_mode: str,
) -> None:
    if repos is None:
        return
    try:
        repos.graph_runs.start_run(
            {
                "run_id": graph_run_id,
                "graph_type": GraphType.ORCHESTRATOR.value,
                "graph_version": "0.1.0",
                "run_name": f"chat.orchestrator.{request_mode}",
                "status": "running",
                "user_id": str(state.get("user_id") or ""),
                "session_id": str(state.get("session_id") or ""),
                "subject_id": normalize_subject_id(state.get("subject_id")),
                "notebook_id": normalize_subject_id(state.get("notebook_id") or state.get("subject_id")),
                "source_policy": _source_policy_from_chat_state(state),
                "request_mode": request_mode,
                "sampled": True,
                "metadata": {"component": "LearningOrchestratorGraph"},
                "inputs_summary": {"has_user_message": bool(state.get("question"))},
            }
        )
    except Exception as exc:
        logger.warning(f"Graph run start failed open: {exc.__class__.__name__}")


def _record_child_facts_safely(
    repos: Any | None,
    state: dict[str, Any],
    graph_result: dict[str, Any],
    *,
    graph_run_id: str,
    request_mode: str,
    latency_ms: int,
    error_type: str,
) -> None:
    if repos is None:
        return
    try:
        child_payload = _child_payload(graph_result)
        for raw_tool_result in list(child_payload.get("tool_results") or []):
            repos.tool_runs.record_tool_run(
                ToolResult.model_validate(raw_tool_result),
                graph_run_id=graph_run_id,
            )
        repos.graph_runs.finish_run(
            graph_run_id,
            {
                "status": "error" if error_type else "completed",
                "latency_ms": latency_ms,
                "error_type": error_type,
                "user_id": str(state.get("user_id") or ""),
                "subject_id": normalize_subject_id(state.get("subject_id")),
                "outputs_summary": {
                    "final_answer_empty": not bool(
                        str((graph_result.get("final_response") or {}).get("answer") or "").strip()
                    ),
                    "intent": _intent(graph_result),
                    "learning_event_count": _learning_event_count(graph_result),
                    "tool_result_count": _tool_result_count(graph_result),
                    "error_count": len(list(graph_result.get("errors") or [])),
                },
            },
        )
    except Exception as exc:
        logger.warning(f"Graph facts recording failed open: {exc.__class__.__name__}")


def _error_orchestrator_result(
    state: dict[str, Any],
    *,
    graph_run_id: str,
    error_type: str,
) -> dict[str, Any]:
    answer = "学习图运行失败，我已安全停止本轮处理，避免给出不可靠结果。"
    return {
        "run_id": graph_run_id,
        "user_id": state.get("user_id") or "",
        "final_response": {
            "answer": answer,
            "source_level": "none",
            "concepts": [],
            "evidence_refs": [],
            "coach_actions": ["retry_later"],
            "mastery_signals": {"signal_strength": "none"},
            "ui_payload": {"target_graph_type": GraphType.ORCHESTRATOR.value, "error_type": error_type},
        },
        "intent_decision": {
            "intent": "fallback",
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "confidence": 1.0,
            "reason": "orchestrator_exception",
        },
        "child_graph_output": {
            "target_graph_type": GraphType.ORCHESTRATOR.value,
            "payload": {"answer": answer},
        },
        "child_graph_result": {
            "task_type": GraphType.ORCHESTRATOR.value,
            "status": "failed",
            "content": {"answer": answer},
            "learning_events": [],
            "audit_event": {"graph_type": GraphType.ORCHESTRATOR.value, "status": "failed"},
            "ui_payload": {"target_graph_type": GraphType.ORCHESTRATOR.value, "error_type": error_type},
            "trace_steps": [{"node": "LearningOrchestratorGraph", "status": "failed"}],
            "error": {
                "code": "orchestrator_runtime_error",
                "message": error_type,
                "node": "LearningOrchestratorGraph",
            },
        },
        "errors": [
            {
                "code": "orchestrator_runtime_error",
                "message": error_type,
                "node": "LearningOrchestratorGraph",
                "severity": "error",
                "metadata": {},
            }
        ],
    }


def _trace_outputs(result: dict[str, Any]) -> dict[str, Any]:
    child_payload = _child_payload(result)
    final_response = result.get("final_response") if isinstance(result.get("final_response"), dict) else {}
    response_ui = final_response.get("ui_payload") if isinstance(final_response.get("ui_payload"), dict) else {}
    runtime_summary = child_payload.get("runtime_summary") if isinstance(child_payload.get("runtime_summary"), dict) else {}
    return {
        "intent": _intent(result),
        "target_graph_type": str((result.get("intent_decision") or {}).get("target_graph_type") or ""),
        "route": _trace_route_from_result(result, final_response),
        "final_answer": str(final_response.get("answer") or ""),
        "final_answer_empty": not bool(str(final_response.get("answer") or "").strip()),
        "safe_reasoning_summary": str(response_ui.get("reasoning_summary") or runtime_summary.get("reasoning_summary") or ""),
        "reasoning_visibility": "safe_summary_only",
        "model_name": _trace_model_name(response_ui, runtime_summary),
        "primary_model_id": str(response_ui.get("primary_model_id") or runtime_summary.get("primary_model_id") or ""),
        "fallback_model_id": str(response_ui.get("fallback_model_id") or runtime_summary.get("fallback_model_id") or ""),
        "fallback_used": bool(response_ui.get("fallback_used") or runtime_summary.get("fallback_used")),
        "fallback_reason": str(response_ui.get("fallback_reason") or runtime_summary.get("fallback_reason") or ""),
        "source_usage": str(response_ui.get("source_usage") or runtime_summary.get("source_usage") or final_response.get("source_level") or ""),
        "retrieval_diagnosis": _trace_retrieval_diagnosis(response_ui, runtime_summary),
        "retrieval_report": _trace_dict(response_ui.get("retrieval_report")),
        "tool_decision": _trace_tool_decision(child_payload, response_ui, runtime_summary),
        "learning_event_count": len(list(child_payload.get("learning_events") or [])),
        "tool_result_count": len(list(child_payload.get("tool_results") or [])),
        "error_count": len(list(result.get("errors") or [])),
    }


def _trace_route_from_result(result: dict[str, Any], final_response: dict[str, Any]) -> str:
    intent = _intent(result)
    if intent == "generate_question":
        return "practice"
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
    child_payload: dict[str, Any],
    response_ui: dict[str, Any],
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    tool_results = [item for item in list(child_payload.get("tool_results") or []) if isinstance(item, dict)]
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


def _trace_inputs(state: dict[str, Any], *, request_mode: str) -> dict[str, Any]:
    question = str(state.get("contextual_question") or state.get("question") or state.get("user_message") or "")
    return {
        "request_mode": request_mode,
        "has_user_message": bool(question),
        "question": question,
        "user_id": str(state.get("user_id") or ""),
        "session_id": str(state.get("session_id") or state.get("thread_id") or ""),
        "subject_id": normalize_subject_id(state.get("subject_id")),
        "subject_name": str(state.get("subject_name") or DEFAULT_SUBJECTS[0]["name"]),
        "model_name": str(state.get("model_name") or ""),
        "thinking_mode": bool(state.get("thinking_mode", False)),
        "source_policy": _source_policy_from_chat_state(state),
        "short_term_context": str(state.get("short_term_context") or ""),
        "session_memory_context": str(state.get("session_memory_context") or ""),
        "long_term_context": str(state.get("long_term_context") or ""),
    }


def _compact_orchestrator_result(result: dict[str, Any]) -> dict[str, Any]:
    child_result = result.get("child_graph_result") if isinstance(result.get("child_graph_result"), dict) else {}
    return {
        "run_id": result.get("run_id"),
        "intent_decision": result.get("intent_decision") or {},
        "child_graph_result": {
            "task_type": child_result.get("task_type"),
            "status": child_result.get("status"),
            "content_keys": sorted((child_result.get("content") or {}).keys())
            if isinstance(child_result.get("content"), dict)
            else [],
        },
        "child_graph_output": {
            "target_graph_type": (result.get("child_graph_output") or {}).get("target_graph_type"),
            "payload_keys": sorted(((result.get("child_graph_output") or {}).get("payload") or {}).keys()),
        },
        "response_envelope_present": bool(result.get("response_envelope")),
        "audit_event_count": len(list(result.get("audit_events") or [])),
        "error_count": len(list(result.get("errors") or [])),
    }


def _child_payload(result: dict[str, Any]) -> dict[str, Any]:
    child_result = result.get("child_graph_result") if isinstance(result.get("child_graph_result"), dict) else {}
    content = child_result.get("content") if isinstance(child_result.get("content"), dict) else {}
    if content:
        return content
    child_output = result.get("child_graph_output") if isinstance(result.get("child_graph_output"), dict) else {}
    payload = child_output.get("payload") if isinstance(child_output.get("payload"), dict) else {}
    return payload


def _intent(result: dict[str, Any]) -> str:
    decision = result.get("intent_decision") if isinstance(result.get("intent_decision"), dict) else {}
    return str(decision.get("intent") or "qa")


def _question_type_from_intent(intent: str, state: dict[str, Any]) -> str:
    if intent == "generate_question":
        return "practice"
    if intent == "evaluate_mastery":
        return "review"
    if intent == "fallback":
        return "meta"
    return str(state.get("question_type") or "concept")


def _route_from_response(response: FinalResponse, intent: str) -> str:
    if intent == "generate_question":
        return "practice"
    if response.source_level.value == "web":
        return "agent"
    if response.source_level.value == "notebook":
        return "rag"
    return "explain"


def _topic(response: FinalResponse, state: dict[str, Any]) -> str:
    if response.concepts:
        return response.concepts[0].name
    question = str(state.get("contextual_question") or state.get("question") or "").strip()
    for prefix in ("什么是", "什么叫", "解释一下", "解释"):
        if question.startswith(prefix):
            return question[len(prefix) :].strip(" ：:？?。.!！") or "当前问题"
    return question[:80] or "当前问题"


def _source_policy_from_chat_state(state: dict[str, Any]) -> str:
    raw = str(state.get("source_policy") or "").strip()
    if raw in {item.value for item in SourcePolicy}:
        return raw
    knowledge_base_mode = _knowledge_base_mode_from_chat_state(state)
    if knowledge_base_mode == "strict":
        return SourcePolicy.NOTEBOOK_ONLY.value
    notebook_policy = str(state.get("notebook_policy") or "").strip()
    search_policy = str(state.get("search_policy") or "").strip()
    question = str(state.get("contextual_question") or state.get("question") or "")
    if notebook_policy == "strict":
        return SourcePolicy.NOTEBOOK_ONLY.value
    if bool(state.get("web_search_requested") or state.get("allow_web")):
        return SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    if notebook_policy == "required":
        return SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    if notebook_policy == "optional" and _has_notebook_signal(question):
        return SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    if search_policy == "required":
        return SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    return SourcePolicy.OPEN_TOOLS.value


def _should_bind_current_notebook_for_question(
    state: dict[str, Any],
    *,
    question: str,
    source_policy: str,
) -> bool:
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return True
    if _knowledge_base_mode_from_chat_state(state) in {"current", "strict"}:
        return True
    notebook_policy = str(state.get("notebook_policy") or "").strip()
    if notebook_policy in {"required", "strict"}:
        return True
    return _has_notebook_signal(question)


def _knowledge_base_mode_from_chat_state(state: dict[str, Any]) -> str:
    candidate = str(state.get("knowledge_base_mode") or "auto").strip().lower()
    if candidate in {"auto", "current", "strict"}:
        return candidate
    return "auto"


def _has_notebook_signal(question: str) -> bool:
    lowered = question.lower()
    material_terms = ("当前 pdf", "当前文档", "notebook", "笔记", "资料", "课件", "课程", "知识库", "上传")
    if any(
        term in question or term in lowered
        for term in material_terms
    ):
        return True
    scoped_reference_terms = (
        "根据我的",
        "依据我的",
        "基于我的",
        "根据这份",
        "依据这份",
        "基于这份",
        "根据当前",
        "依据当前",
        "基于当前",
    )
    return any(term in question or term in lowered for term in scoped_reference_terms)


def _learning_event_count(result: dict[str, Any]) -> int:
    return len(list(_child_payload(result).get("learning_events") or []))


def _tool_result_count(result: dict[str, Any]) -> int:
    return len(list(_child_payload(result).get("tool_results") or []))
