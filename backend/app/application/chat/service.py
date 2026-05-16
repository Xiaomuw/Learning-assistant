from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

from app.application.chat.messages import normalize_explanation_payload
from app.application.chat.orchestrator_runtime import run_orchestrator_chat, stream_orchestrator_chat
from app.application.chat.persistence import persist_chat_session
from app.application.chat.state_builder import build_initial_state
from app.infrastructure.llm.config import is_chat_sync_fast_concept_fallback_enabled
from app.domains.practice.service import normalize_quiz_item
from app.shared.schemas.contracts import ChatExecutionResult, UserMemoryRecord


_STREAM_DONE = object()


def run_chat_once(
    *,
    user_id: str,
    session_id: str,
    question: str,
    subject_id: str,
    thinking_mode: bool = False,
    allow_web: bool = False,
    client_request_id: str | None = None,
    request_id: str | None = None,
) -> ChatExecutionResult:
    result, _ = run_chat_once_with_state(
        user_id=user_id,
        session_id=session_id,
        question=question,
        subject_id=subject_id,
        thinking_mode=thinking_mode,
        allow_web=allow_web,
        client_request_id=client_request_id,
        request_id=request_id,
        persist=True,
    )
    return result


def run_chat_once_with_state(
    *,
    user_id: str,
    session_id: str,
    question: str,
    subject_id: str,
    thinking_mode: bool = False,
    allow_web: bool = False,
    client_request_id: str | None = None,
    request_id: str | None = None,
    persist: bool = True,
) -> tuple[ChatExecutionResult, dict[str, Any]]:
    initial_state = build_initial_state(
        user_id=user_id,
        session_id=session_id,
        question=question,
        subject_id=subject_id,
        request_mode="sync",
        thinking_mode=thinking_mode,
        allow_web=allow_web,
        client_request_id=client_request_id,
        request_id=request_id,
    )
    initial_state["sync_fast_concept_fallback"] = is_chat_sync_fast_concept_fallback_enabled()
    final_state = run_orchestrator_chat(initial_state, request_mode="sync")
    if persist:
        persist_chat_session(
            user_id=user_id,
            session_id=session_id,
            subject_id=subject_id,
            question=question,
            final_state=final_state,
        )
    return _chat_execution_result_from_state(session_id=session_id, final_state=final_state), final_state


def _chat_execution_result_from_state(*, session_id: str, final_state: dict[str, Any]) -> ChatExecutionResult:
    return ChatExecutionResult(
        session_id=session_id,
        question_type=str(final_state.get("question_type", "concept") or "concept"),
        route=str(final_state.get("route", "explain") or "explain"),
        final_answer=str(final_state.get("final_answer") or ""),
        explanation=normalize_explanation_payload(final_state.get("explanation")),
        quiz_items=[normalize_quiz_item(item) for item in (final_state.get("quiz_items") or [])],
        quiz_request=final_state.get("quiz_request"),
        quiz_clarification=final_state.get("quiz_clarification"),
        memory=UserMemoryRecord.model_validate(final_state.get("memory") or {}),
    )


async def stream_chat(
    *,
    user_id: str,
    session_id: str,
    question: str,
    subject_id: str,
    thinking_mode: bool = False,
    allow_web: bool = False,
    client_request_id: str | None = None,
    request_id: str | None = None,
    stream_writer: Callable[[dict[str, Any]], None] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    initial_state = build_initial_state(
        user_id=user_id,
        session_id=session_id,
        question=question,
        subject_id=subject_id,
        request_mode="sse",
        thinking_mode=thinking_mode,
        allow_web=allow_web,
        client_request_id=client_request_id,
        request_id=request_id,
    )
    if callable(stream_writer):
        initial_state["stream_writer"] = stream_writer
    final_state: dict[str, Any] | None = None
    async for chunk in _async_stream_orchestrator_chunks(initial_state):
        state_update = chunk.get("state_update") if isinstance(chunk.get("state_update"), dict) else {}
        if isinstance(state_update.get("__final_state"), dict):
            final_state = dict(state_update["__final_state"])
        yield chunk
    if final_state is None:
        final_state = run_orchestrator_chat(initial_state, request_mode="sse")
    persist_chat_session(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        question=question,
        final_state=final_state,
    )


async def _async_stream_orchestrator_chunks(initial_state: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
    iterator = stream_orchestrator_chat(initial_state, request_mode="sse")
    while True:
        chunk = await asyncio.to_thread(_next_stream_chunk, iterator)
        if chunk is _STREAM_DONE:
            break
        yield chunk


def _next_stream_chunk(iterator: Any) -> dict[str, Any] | object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_DONE


def _stream_chunks_from_final_state(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    question_type = str(final_state.get("question_type") or "concept")
    route = str(final_state.get("route") or "explain")
    runtime = final_state.get("graph_runtime") if isinstance(final_state.get("graph_runtime"), dict) else {}
    elapsed = float(runtime.get("latency_ms") or 0) / 1000
    quiz_items = list(final_state.get("quiz_items") or [])
    chunks: list[dict[str, Any]] = [
        {
            "node": "router",
            "state_update": {
                "question_type": question_type,
                "route": route,
                "source_policy": str(final_state.get("source_policy") or ""),
                "orchestrator_result": final_state.get("orchestrator_result") or {},
            },
            "elapsed": 0.0,
        }
    ]
    quiz_request = final_state.get("quiz_request") if isinstance(final_state.get("quiz_request"), dict) else None
    quiz_clarification = (
        final_state.get("quiz_clarification") if isinstance(final_state.get("quiz_clarification"), dict) else None
    )
    if quiz_items or quiz_clarification:
        quiz_generation_status = (
            final_state.get("quiz_generation_status")
            if isinstance(final_state.get("quiz_generation_status"), dict)
            else {}
        )
        if not quiz_generation_status:
            quiz_generation_status = {
                "generated_count": len(quiz_items),
                "source": "LearningOrchestratorGraph",
            }
        chunks.append(
            {
                "node": "quiz_output_node",
                "state_update": {
                    "question_type": question_type,
                    "route": route,
                    "quiz_items": quiz_items,
                    "quiz_request": quiz_request,
                    "quiz_clarification": quiz_clarification,
                    "final_answer": str(final_state.get("final_answer") or ""),
                    "quiz_generation_status": quiz_generation_status,
                },
                "elapsed": elapsed,
            }
        )
    else:
        chunks.append(
            {
                "node": "qa_agent_node",
                "state_update": {
                    "question_type": question_type,
                    "route": route,
                    "explanation": final_state.get("explanation") or {},
                    "final_answer": str(final_state.get("final_answer") or ""),
                    "execution_mode": "orchestrator_graph",
                    "degraded": bool(final_state.get("graph_warnings")),
                    "selected_model_profile": final_state.get("selected_model_profile") or {},
                    "primary_model_id": str(final_state.get("primary_model_id") or ""),
                    "fallback_model_id": str(final_state.get("fallback_model_id") or ""),
                    "fallback_used": bool(final_state.get("fallback_used", False)),
                    "fallback_reason": str(final_state.get("fallback_reason") or ""),
                    "model_attempts": list(final_state.get("model_attempts") or []),
                },
                "elapsed": elapsed,
            }
        )
    chunks.extend(
        [
            {
                "node": "memory_node",
                "state_update": {"memory": final_state.get("memory") or {}},
                "elapsed": elapsed,
            },
            {
                "node": "finalize_node",
                "state_update": {
                    "finalized": True,
                    "final_response_type": "orchestrator_graph",
                    "degraded": bool(final_state.get("graph_warnings")),
                },
                "elapsed": elapsed,
            },
        ]
    )
    return chunks
