from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

import app.interfaces.api.chat as chat_module
from app.interfaces.api.chat import ChatRequest, router as chat_router
from app.application.chat import messages as chat_messages
from app.application.chat.orchestrator_runtime import _chat_state_from_orchestrator_result, _trace_outputs
from app.application.chat import service as chat_service
from app.application.chat import state_builder as chat_state_builder
from app.interfaces.auth.dependencies import require_current_user
from app.interfaces.middleware.request_logging import RequestLoggingMiddleware
from app.shared.schemas.contracts import (
    AuthUserView,
    ChatExecutionResult,
    ExplanationPayload,
    QuizClarificationPanel,
    QuizRequestResolution,
    UserMemoryRecord,
)


async def _fake_stream_workflow(**_kwargs):
    yield {"node": "router", "state_update": {"question_type": "smalltalk"}, "elapsed": 0.01}
    yield {
        "node": "meta_node",
        "state_update": {
            "explanation": {"topic": "寒暄", "thinking": "你好，我在。", "steps": [], "mistakes": "", "similar": []},
            "final_answer": "你好，我已经在线。",
        },
        "elapsed": 0.02,
    }


async def _fake_stream_failure(**_kwargs):
    raise RuntimeError("401: model is not available for your subscription tier")
    yield {"node": "never", "state_update": {}, "elapsed": 0.0}


async def _fake_stream_with_slow_first_chunk(**_kwargs):
    await asyncio.sleep(0.02)
    yield {"node": "router", "state_update": {"question_type": "concept"}, "elapsed": 0.02}


class _CloseGuardedStream:
    def __init__(self, pending_task: asyncio.Task) -> None:
        self.pending_task = pending_task
        self.closed = False

    async def aclose(self) -> None:
        if not self.pending_task.done():
            raise RuntimeError("aclose(): asynchronous generator is already running")
        self.closed = True


class _FakeStreamChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeStreamingLLM:
    def __init__(self, chunks: list[str], invoke_text: str = "HTTP fallback answer") -> None:
        self.chunks = chunks
        self.invoke_text = invoke_text

    def stream(self, _messages):
        for chunk in self.chunks:
            yield _FakeStreamChunk(chunk)

    def invoke(self, _messages):
        return self.invoke_text


def _state_from_chat_result(result: ChatExecutionResult) -> dict:
    return {
        "question_type": result.question_type,
        "route": result.route,
        "final_answer": result.final_answer,
        "explanation": result.explanation.model_dump(),
        "quiz_items": [item.model_dump() for item in result.quiz_items],
        "quiz_request": result.quiz_request.model_dump() if result.quiz_request else None,
        "quiz_clarification": result.quiz_clarification.model_dump() if result.quiz_clarification else None,
        "memory": result.memory.model_dump(),
    }


def _chat_result_with_state(result: ChatExecutionResult) -> tuple[ChatExecutionResult, dict]:
    return result, _state_from_chat_result(result)


class _RuntimeWriterTokenIterator:
    def __init__(self, initial_state: dict) -> None:
        self.initial_state = initial_state
        self.index = 0
        self.final_state = {
            "question_type": "concept",
            "route": "explain",
            "explanation": {},
            "final_answer": "HTTP 是应用层协议。",
            "quiz_items": [],
            "memory": {},
            "streaming_mode": "token",
            "streaming_token_count": 1,
        }

    def __iter__(self):
        return self

    def __next__(self):
        if self.index == 0:
            writer = self.initial_state.get("stream_writer")
            if callable(writer):
                writer(
                    {
                        "event": "answer_delta",
                        "data": {
                            "delta": "HTTP 是",
                            "streaming_mode": "token",
                            "is_synthetic_delta": False,
                        },
                    }
                )
            time.sleep(0.02)
            self.index += 1
            return {
                "node": "qa_agent_node",
                "state_update": {
                    "question_type": "concept",
                    "route": "explain",
                    "explanation": {},
                    "final_answer": "HTTP 是应用层协议。",
                    "streaming_mode": "token",
                },
                "elapsed": 0.03,
            }
        if self.index == 1:
            self.index += 1
            return {
                "node": "finalize_node",
                "state_update": {
                    "finalized": True,
                    "__final_state": self.final_state,
                },
                "elapsed": 0.04,
            }
        if self.index == 2:
            self.index += 1
            return {
                "node": "final",
                "state_update": {
                    "finalized": True,
                    "question_type": "concept",
                    "route": "explain",
                    "final_answer": "HTTP 是应用层协议。",
                    "streaming_mode": "token",
                    "streaming_token_count": 1,
                },
                "elapsed": 0.04,
            }
        raise StopIteration


class ChatApiTest(unittest.TestCase):
    def setUp(self) -> None:
        AppStatus.should_exit_event = None
        chat_module._RUNNING_CHAT_JOBS.clear()
        self.chat_jobs: dict[str, dict] = {}

        def _create_chat_job(
            *,
            job_id: str,
            user_id: str,
            session_id: str,
            request_id: str,
            conversation_id: str | None = None,
            client_request_id: str | None = None,
            request_payload: dict | None = None,
            trace_id: str | None = None,
            expires_at=None,
        ):
            self.chat_jobs.setdefault(
                job_id,
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "conversation_id": conversation_id or session_id,
                    "client_request_id": client_request_id,
                    "request_id": request_id,
                    "trace_id": trace_id or request_id,
                    "status": "pending",
                    "request_payload": dict(request_payload or {}),
                    "final_answer": "",
                    "error_code": "",
                    "error_message": "",
                    "route": "",
                    "result_json": None,
                    "error_json": None,
                    "expires_at": expires_at,
                },
            )
            return dict(self.chat_jobs[job_id])

        def _get_chat_job(*, user_id: str, job_id: str):
            row = self.chat_jobs.get(job_id)
            if not row or row["user_id"] != user_id:
                return None
            return dict(row)

        def _mark_chat_job_completed(*, job_id: str, result: dict):
            self.chat_jobs[job_id]["status"] = "completed"
            self.chat_jobs[job_id]["result_json"] = dict(result)
            self.chat_jobs[job_id]["error_json"] = None
            self.chat_jobs[job_id]["final_answer"] = str(result.get("final_answer") or "")
            self.chat_jobs[job_id]["route"] = str(result.get("route") or "")
            self.chat_jobs[job_id]["error_code"] = ""
            self.chat_jobs[job_id]["error_message"] = ""

        def _mark_chat_job_failed(*, job_id: str, error: dict):
            self.chat_jobs[job_id]["status"] = "failed"
            self.chat_jobs[job_id]["error_json"] = dict(error)
            self.chat_jobs[job_id]["error_code"] = str(error.get("code") or error.get("reason") or "")
            self.chat_jobs[job_id]["error_message"] = str(error.get("error") or error.get("message") or "")

        app = FastAPI()
        app.include_router(chat_router, prefix="/api")
        app.add_middleware(RequestLoggingMiddleware)
        app.dependency_overrides[require_current_user] = lambda: AuthUserView(
            id="default_user",
            email="default@example.com",
            display_name="测试用户",
            status="active",
        )
        self.app = app
        self.client = TestClient(app)
        self.common_patches = [
            patch(
                "app.application.chat.state_builder.get_subject_record",
                return_value=type(
                    "_Subject",
                    (),
                    {"name": "数据结构与算法", "description": "线性表、树、图、排序、查找等"},
                )(),
            ),
            patch(
                "app.application.chat.state_builder.build_request_context",
                return_value={
                    "memory": {
                        "weak_points": [],
                        "error_count": {},
                        "recent_topics": [],
                        "last_session": "",
                    },
                    "user_profile": {
                        "agent_style_name": "",
                        "agent_style_prompt": "",
                        "display_name": "测试用户",
                        "onboarding_completed": True,
                    },
                    "existing_session": {
                        "messages": [
                            {"role": "user", "content": "什么是 HTTP？"},
                            {
                                "role": "assistant",
                                "content": "HTTP 是应用层协议。",
                                "explanation": {"topic": "HTTP"},
                            },
                        ],
                        "session_memory": {
                            "summary_text": "当前会话正在围绕 HTTP 学习。",
                            "active_topic": "HTTP",
                            "current_goal": "理解 HTTP 的基本概念",
                            "open_loops": ["继续追问缓存与连接管理"],
                            "resolved_points": ["已经解释了 HTTP 是应用层协议"],
                            "last_question_type": "concept",
                            "last_updated_at": "2026-04-15T00:00:00Z",
                        },
                    },
                    "short_term_messages": [
                        {"role": "user", "content": "什么是 HTTP？"},
                        {
                            "role": "assistant",
                            "content": "HTTP 是应用层协议。",
                            "explanation": {"topic": "HTTP"},
                        },
                    ],
                    "short_term_context": "学生1: 什么是 HTTP？\n助手2（主题：HTTP）: HTTP 是应用层协议。",
                    "session_memory": {
                        "summary_text": "当前会话正在围绕 HTTP 学习。",
                        "active_topic": "HTTP",
                        "current_goal": "理解 HTTP 的基本概念",
                        "open_loops": ["继续追问缓存与连接管理"],
                        "resolved_points": ["已经解释了 HTTP 是应用层协议"],
                        "last_question_type": "concept",
                        "last_updated_at": "2026-04-15T00:00:00Z",
                    },
                    "session_memory_context": (
                        "会话摘要：当前会话正在围绕 HTTP 学习。\n"
                        "当前主主题：HTTP\n"
                        "当前学习目标：理解 HTTP 的基本概念\n"
                        "未解决点：继续追问缓存与连接管理\n"
                        "已解决要点：已经解释了 HTTP 是应用层协议"
                    ),
                    "long_term_context": "用户昵称：测试用户",
                },
            ),
            patch(
                "app.application.chat.persistence.update_memories_after_turn",
                return_value={
                    "session_memory": {
                        "summary_text": "当前会话正在围绕 HTTP 学习。",
                        "active_topic": "HTTP",
                        "current_goal": "理解 HTTP 的基本概念",
                        "open_loops": ["继续追问缓存与连接管理"],
                        "resolved_points": ["已经解释了 HTTP 是应用层协议"],
                        "last_question_type": "concept",
                        "last_updated_at": "2026-04-15T00:00:00Z",
                    },
                    "session_memory_context": "当前主主题：HTTP",
                },
            ),
            patch(
                "app.application.chat.persistence.append_chat_turn_record",
                return_value=type("_Session", (), {"model_dump": lambda self: {}})(),
            ),
            patch(
                "app.application.chat.state_builder.resolve_active_chat_model",
                return_value="openai-gpt-oss-20b",
            ),
            patch("app.interfaces.api.chat.create_chat_async_job", side_effect=_create_chat_job),
            patch("app.interfaces.api.chat.get_chat_async_job", side_effect=_get_chat_job),
            patch("app.interfaces.api.chat.mark_chat_async_job_completed", side_effect=_mark_chat_job_completed),
            patch("app.interfaces.api.chat.mark_chat_async_job_failed", side_effect=_mark_chat_job_failed),
        ]
        for item in self.common_patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.common_patches):
            item.stop()

    def test_chat_sync_returns_final_payload(self) -> None:
        final_state = ChatExecutionResult(
            session_id="session-1",
            question_type="concept",
            explanation=ExplanationPayload(
                topic="HTTP",
                thinking="HTTP 是应用层协议。",
                steps=["定义请求与响应语义"],
                mistakes="不要把 HTTP 误认为传输层协议",
                similar=["HTTPS"],
            ),
            quiz_items=[],
            memory=UserMemoryRecord(
                weak_points=[],
                error_count={},
                recent_topics=["HTTP"],
                last_session="abc",
            ),
        )
        state = _state_from_chat_result(final_state)
        state.update(
            {
                "web_search_attempted": True,
                "web_search_used": True,
                "external_tool_calls": [
                    {
                        "capability": "web_search",
                        "provider": "mcp",
                        "status": "success",
                        "doc_count": 3,
                        "args": {"query": "不应暴露原始查询"},
                    }
                ],
                "execution_mode": "direct_answer",
                "reasoning_summary": "模型直接回答。",
                "source_usage": "model",
                "selected_model_profile": {"model_id": "deepseek-v4-pro", "family": "V4"},
                "primary_model_id": "deepseek-v4-pro",
                "model_attempts": [{"model_id": "deepseek-v4-pro", "role": "primary", "status": "ok"}],
                "model_latency_ms": 1234,
            }
        )
        with patch("app.interfaces.api.chat.run_chat_once_with_state", return_value=(final_state, state)):
            response = self.client.post(
                "/api/chat/sync",
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("x-request-id"))
        payload = response.json()
        self.assertEqual(payload["question_type"], "concept")
        self.assertEqual(payload["explanation"]["topic"], "HTTP")
        self.assertTrue(payload["web_search_attempted"])
        self.assertTrue(payload["web_search_used"])
        self.assertEqual(payload["external_tool_calls"][0]["capability"], "web_search")
        self.assertEqual(payload["external_tool_calls"][0]["source"], "web")
        self.assertEqual(payload["external_tool_calls"][0]["doc_count"], 3)
        self.assertNotIn("provider", payload["external_tool_calls"][0])
        self.assertNotIn("args", payload["external_tool_calls"][0])
        self.assertEqual(payload["execution_mode"], "direct_answer")
        self.assertEqual(payload["reasoning_summary"], "模型直接回答。")
        self.assertEqual(payload["source_usage"], "model")
        self.assertEqual(payload["selected_model_profile"]["model_id"], "deepseek-v4-pro")
        self.assertEqual(payload["model_attempts"][0]["status"], "ok")
        self.assertEqual(payload["model_latency_ms"], 1234)

    def test_chat_sync_reuses_request_id_header(self) -> None:
        final_state = ChatExecutionResult(
            session_id="session-1",
            question_type="concept",
            explanation=ExplanationPayload(
                topic="HTTP",
                thinking="HTTP 是应用层协议。",
                steps=["定义请求与响应语义"],
                mistakes="不要把 HTTP 误认为传输层协议",
                similar=["HTTPS"],
            ),
            quiz_items=[],
            memory=UserMemoryRecord(
                weak_points=[],
                error_count={},
                recent_topics=["HTTP"],
                last_session="abc",
            ),
        )
        with patch(
            "app.interfaces.api.chat.run_chat_once_with_state",
            return_value=_chat_result_with_state(final_state),
        ) as run_once:
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-test-request-1"},
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-request-id"), "weapp-test-request-1")
        _, kwargs = run_once.call_args
        self.assertEqual(kwargs["request_id"], "weapp-test-request-1")

    def test_chat_sync_sanitizes_provider_error_detail(self) -> None:
        with patch(
            "app.interfaces.api.chat.run_chat_once_with_state",
            side_effect=RuntimeError("APITimeoutError: Request timed out after 60s"),
        ):
            response = self.client.post(
                "/api/chat/sync",
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertIn("模型响应超时", payload["error"])
        self.assertEqual(payload["reason"], "timeout")
        self.assertTrue(payload["retryable"])
        self.assertTrue(payload["request_id"])
        self.assertNotIn("APITimeoutError", payload["error"])
        self.assertNotIn("Request timed out", payload["error"])

    def test_chat_sync_returns_pending_when_inline_budget_exceeded(self) -> None:
        def _slow_chat_once(**_kwargs):
            time.sleep(0.05)
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-1",
                question_type="concept",
                route="explain",
                final_answer="HTTP 是应用层协议。",
                explanation=ExplanationPayload(topic="HTTP"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with (
            patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_slow_chat_once),
            patch("app.interfaces.api.chat.get_chat_sync_inline_budget_seconds", return_value=0.01),
            patch("app.interfaces.api.chat._get_chat_sync_completion_grace_seconds", return_value=0.01),
            patch("app.interfaces.api.chat.get_chat_sync_poll_retry_after_ms", return_value=1000),
        ):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-pending-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-1",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["job_id"], "weapp-pending-1")
        self.assertEqual(payload["retry_after_ms"], 1000)
        self.assertIn("后台继续处理", payload["explanation"]["thinking"])
        self.assertEqual(payload["trace_records"][0]["stage"], "mobile_sync_delivery")
        self.assertEqual(payload["trace_records"][0]["final_response_status"], "pending")

        self.chat_jobs["weapp-pending-1"]["status"] = "completed"
        self.chat_jobs["weapp-pending-1"]["result_json"] = {
            "session_id": "session-1",
            "question_type": "concept",
            "route": "explain",
            "final_answer": "HTTP 是应用层协议。",
            "explanation": {"topic": "HTTP"},
            "quiz_items": [],
            "memory": {},
            "status": "completed",
            "job_id": "weapp-pending-1",
            "request_id": "weapp-pending-1",
        }
        job_response = self.client.post("/api/chat/jobs/weapp-pending-1/poll")
        self.assertEqual(job_response.status_code, 200)
        job_payload = job_response.json()
        self.assertEqual(job_payload["status"], "completed")
        self.assertEqual(job_payload["response"]["final_answer"], "HTTP 是应用层协议。")

    def test_chat_sync_cleans_duplicate_final_answer(self) -> None:
        def _duplicated_chat_once(**_kwargs):
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-dedupe",
                question_type="simple_fact",
                route="direct",
                final_answer="1 + 1 = 2。 1 + 1 = 2。",
                explanation=ExplanationPayload(topic="简单计算"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_duplicated_chat_once):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-dedupe-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-dedupe",
                    "question": "1+1等于多少",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["final_answer"], "1 + 1 = 2。")
        self.assertNotIn("递归", payload["final_answer"])
        self.assertNotIn("链表", payload["final_answer"])

    def test_chat_sync_uses_steps_when_final_answer_is_planning_text(self) -> None:
        def _planning_chat_once(**_kwargs):
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-planning",
                question_type="concept",
                route="explain",
                final_answer="用户想了解 HTTP 的基本概念。",
                explanation=ExplanationPayload(
                    topic="HTTP",
                    thinking="用户想了解 HTTP 的基本概念，需要从定义和作用几个方面讲解。",
                    steps=[
                        "HTTP 是互联网通信的基础协议，需要从定义、作用几个方面来讲解。",
                        "客户端发送请求，服务器返回响应。",
                        "客户端发送请求，服务器返回响应。",
                    ],
                    mistakes="不要把 HTTP 当成传输层协议。",
                    similar=["HTTPS", "TCP"],
                ),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_planning_chat_once):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-planning-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-planning",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("HTTP 是互联网通信的基础协议", payload["final_answer"])
        self.assertIn("客户端发送请求，服务器返回响应", payload["final_answer"])
        self.assertNotIn("用户想了解", payload["final_answer"])
        self.assertNotIn("需要从", payload["final_answer"])
        self.assertEqual(payload["final_answer"].count("客户端发送请求"), 1)

    def test_chat_sync_prefers_steps_when_concept_answer_starts_with_long_analogy(self) -> None:
        def _analogy_chat_once(**_kwargs):
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-analogy",
                question_type="concept",
                route="explain",
                final_answer=(
                    "想象你在餐厅点餐：你是顾客，厨房是服务器，而服务员就是 HTTP。"
                    "你想吃一份牛排，需要告诉服务员，服务员把要求送到厨房，再把做好的牛排端回来。"
                ),
                explanation=ExplanationPayload(
                    topic="HTTP",
                    thinking="用户想了解 HTTP。",
                    steps=[
                        "HTTP 是 Web 中客户端和服务器之间通信的应用层协议。",
                        "它采用请求-响应模型：浏览器发出请求，服务器返回响应。",
                        "HTTP 本身无状态，常见易错点是不要把它当成传输层协议。",
                    ],
                    mistakes="不要把 HTTP 当成传输层协议。",
                    similar=["HTTPS", "TCP"],
                ),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_analogy_chat_once):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-analogy-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-analogy",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("HTTP 是 Web 中客户端和服务器之间通信的应用层协议", payload["final_answer"])
        self.assertIn("请求-响应模型", payload["final_answer"])
        self.assertIn("无状态", payload["final_answer"])
        self.assertNotIn("餐厅", payload["final_answer"])
        self.assertNotIn("点餐", payload["final_answer"])

    def test_chat_sync_reorders_concept_answer_when_why_section_comes_first(self) -> None:
        def _why_first_chat_once(**_kwargs):
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-why-first",
                question_type="concept",
                route="explain",
                final_answer=(
                    "为什么需要HTTP：浏览器和服务器之间需要一种共同规则来交换网页资源。"
                    "HTTP就是这种规则，让不同设备和软件能可靠沟通。"
                    "HTTP是什么：HTTP 全称是超文本传输协议，是 Web 中客户端和服务器之间通信的应用层协议。"
                    "HTTP如何工作：客户端发送请求，服务器返回响应，响应里包含状态码、响应头和资源内容。"
                ),
                explanation=ExplanationPayload(topic="HTTP"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_why_first_chat_once):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-why-first-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-why-first",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["final_answer"].startswith("HTTP是什么"))
        self.assertLess(payload["final_answer"].find("HTTP是什么"), payload["final_answer"].find("为什么需要HTTP"))
        self.assertIn("应用层协议", payload["final_answer"])
        self.assertIn("请求，服务器返回响应", payload["final_answer"])

    def test_chat_sync_empty_final_answer_does_not_fall_back_to_thinking(self) -> None:
        def _empty_final_chat_once(**_kwargs):
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-empty-final",
                question_type="concept",
                route="explain",
                final_answer="",
                explanation=ExplanationPayload(
                    topic="HTTP",
                    thinking="用户想了解 HTTP 的基本概念。",
                    steps=[
                        "HTTP 是应用层协议。",
                        "它使用请求-响应模型，在客户端和服务器之间传递消息。",
                    ],
                    mistakes="不要把 HTTP 当成传输层协议。",
                    similar=["HTTPS", "TCP"],
                ),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_empty_final_chat_once):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-empty-final-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-empty-final",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["final_answer"],
            "HTTP 是应用层协议。\n\n它使用请求-响应模型，在客户端和服务器之间传递消息。",
        )
        self.assertNotIn("用户想了解", payload["final_answer"])

    def test_chat_job_poll_cleans_duplicate_completed_result(self) -> None:
        self.chat_jobs["dedupe-job-1"] = {
            "job_id": "dedupe-job-1",
            "user_id": "default_user",
            "session_id": "session-1",
            "request_id": "dedupe-request-1",
            "status": "completed",
            "result_json": {
                "session_id": "session-1",
                "question_type": "concept",
                "route": "explain",
                "final_answer": "HTTP 是应用层协议。 HTTP 是应用层协议。",
                "explanation": {
                    "topic": "HTTP",
                    "final_answer": "HTTP 是应用层协议。 HTTP 是应用层协议。",
                },
                "quiz_items": [],
                "memory": {},
                "status": "completed",
                "job_id": "dedupe-job-1",
                "request_id": "dedupe-request-1",
            },
            "error_json": None,
        }

        response = self.client.post("/api/chat/jobs/dedupe-job-1/poll")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["response"]["final_answer"], "HTTP 是应用层协议。")
        self.assertEqual(payload["response"]["explanation"]["final_answer"], "HTTP 是应用层协议。")

    def test_chat_sync_returns_completed_when_finished_during_grace(self) -> None:
        def _nearly_slow_chat_once(**_kwargs):
            time.sleep(0.03)
            result, state = _chat_result_with_state(ChatExecutionResult(
                session_id="session-grace",
                question_type="smalltalk",
                route="explain",
                final_answer="你好，我在。",
                explanation=ExplanationPayload(topic="问候"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))
            state["trace_records"] = [
                {"stage": "answer_quality_check", "answer_quality_status": "pass", "passed": True},
                {"stage": "final_response", "final_response_status": "completed"},
            ]
            return result, state

        with (
            patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_nearly_slow_chat_once),
            patch("app.interfaces.api.chat.get_chat_sync_inline_budget_seconds", return_value=0.01),
            patch("app.interfaces.api.chat._get_chat_sync_completion_grace_seconds", return_value=0.2),
        ):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "weapp-grace-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-grace",
                    "question": "你好",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["job_id"], "weapp-grace-1")
        self.assertEqual(payload["final_answer"], "你好，我在。")
        self.assertEqual(payload["trace_records"][-1]["final_response_status"], "completed")
        self.assertEqual(self.chat_jobs["weapp-grace-1"]["status"], "completed")

    def test_chat_job_poll_rejects_other_user(self) -> None:
        self.chat_jobs["user-owned-job"] = {
            "job_id": "user-owned-job",
            "user_id": "default_user",
            "session_id": "session-1",
            "request_id": "user-owned-job",
            "status": "completed",
            "result_json": {
                "session_id": "session-1",
                "question_type": "concept",
                "route": "explain",
                "final_answer": "HTTP 是应用层协议。",
                "explanation": {"topic": "HTTP"},
                "quiz_items": [],
                "memory": {},
                "status": "completed",
                "job_id": "user-owned-job",
                "request_id": "user-owned-job",
            },
            "error_json": None,
        }
        self.app.dependency_overrides[require_current_user] = lambda: AuthUserView(
            id="other_user",
            email="other@example.com",
            display_name="其他用户",
            status="active",
        )
        try:
            response = self.client.post("/api/chat/jobs/user-owned-job/poll")
        finally:
            self.app.dependency_overrides[require_current_user] = lambda: AuthUserView(
                id="default_user",
                email="default@example.com",
                display_name="测试用户",
                status="active",
            )

        self.assertEqual(response.status_code, 404)

    def test_chat_job_poll_returns_failed_error(self) -> None:
        self.chat_jobs["failed-job-1"] = {
            "job_id": "failed-job-1",
            "user_id": "default_user",
            "session_id": "session-1",
            "request_id": "failed-request-1",
            "status": "failed",
            "result_json": None,
            "error_json": {
                "code": "model_unavailable",
                "error": "模型服务暂时不可用",
                "reason": "model_unavailable",
                "retryable": True,
                "request_id": "failed-request-1",
            },
            "expires_at": None,
        }

        response = self.client.post("/api/chat/jobs/failed-job-1/poll")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "model_unavailable")
        self.assertTrue(payload["retryable"])

    def test_chat_job_poll_returns_typed_expired_error(self) -> None:
        self.chat_jobs["expired-job-1"] = {
            "job_id": "expired-job-1",
            "user_id": "default_user",
            "session_id": "session-1",
            "request_id": "expired-request-1",
            "status": "pending",
            "result_json": None,
            "error_json": None,
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        }

        response = self.client.post("/api/chat/jobs/expired-job-1/poll")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "chat_job_expired")
        self.assertEqual(payload["error"]["reason"], "expired")
        self.assertFalse(payload["retryable"])
        self.assertGreater(payload["retry_after_ms"], 0)
        self.assertEqual(self.chat_jobs["expired-job-1"]["status"], "failed")

    def test_chat_sync_deduplicates_same_client_request_id(self) -> None:
        def _slow_chat_once(**_kwargs):
            time.sleep(0.08)
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-idempotent",
                question_type="concept",
                route="explain",
                final_answer="HTTP 是应用层协议。",
                explanation=ExplanationPayload(topic="HTTP"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        body = {
            "user_id": "default_user",
            "session_id": "session-idempotent",
            "question": "什么是 HTTP？",
            "subject_id": "general",
            "client_request_id": "client-turn-42",
        }
        with (
            patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_slow_chat_once),
            patch("app.interfaces.api.chat.get_chat_sync_inline_budget_seconds", return_value=0.01),
            patch("app.interfaces.api.chat._get_chat_sync_completion_grace_seconds", return_value=0.01),
            patch("app.interfaces.api.chat.get_chat_sync_poll_retry_after_ms", return_value=1000),
        ):
            first = self.client.post("/api/chat/sync", headers={"X-Request-ID": "req-a"}, json=body)
            second = self.client.post("/api/chat/sync", headers={"X-Request-ID": "req-b"}, json=body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_payload = first.json()
        second_payload = second.json()
        self.assertEqual(first_payload["status"], "pending")
        self.assertEqual(second_payload["status"], "pending")
        self.assertEqual(first_payload["job_id"], second_payload["job_id"])
        self.assertEqual(len(self.chat_jobs), 1)
        job = self.chat_jobs[first_payload["job_id"]]
        self.assertEqual(job["client_request_id"], "client-turn-42")
        self.assertEqual(job["conversation_id"], "session-idempotent")
        self.assertEqual(job["trace_id"], "req-a")
        self.assertEqual(job["request_payload"]["question"], "什么是 HTTP？")
        self.assertEqual(job["request_payload"]["client_request_id"], "client-turn-42")

    def test_chat_sync_persists_durable_job_payload_for_pending_response(self) -> None:
        def _slow_chat_once(**_kwargs):
            time.sleep(0.05)
            return _chat_result_with_state(ChatExecutionResult(
                session_id="session-durable",
                question_type="concept",
                route="explain",
                final_answer="HTTP 是应用层协议。",
                explanation=ExplanationPayload(topic="HTTP"),
                quiz_items=[],
                memory=UserMemoryRecord(),
            ))

        with (
            patch("app.interfaces.api.chat.run_chat_once_with_state", side_effect=_slow_chat_once),
            patch("app.interfaces.api.chat.get_chat_sync_inline_budget_seconds", return_value=0.01),
            patch("app.interfaces.api.chat._get_chat_sync_completion_grace_seconds", return_value=0.01),
        ):
            response = self.client.post(
                "/api/chat/sync",
                headers={"X-Request-ID": "durable-request-1", "X-Client-Request-ID": "durable-client-1"},
                json={
                    "user_id": "default_user",
                    "session_id": "session-durable",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        job = self.chat_jobs[payload["job_id"]]
        self.assertEqual(job["user_id"], "default_user")
        self.assertEqual(job["conversation_id"], "session-durable")
        self.assertEqual(job["client_request_id"], "durable-client-1")
        self.assertEqual(job["request_payload"]["request_id"], "durable-request-1")
        self.assertEqual(job["request_payload"]["client_request_id"], "durable-client-1")
        self.assertIsNotNone(job["expires_at"])

    def test_run_chat_async_job_marks_completed(self) -> None:
        body = ChatRequest(
            user_id="default_user",
            session_id="session-async",
            question="什么是 HTTP？",
            subject_id="general",
        )
        self.chat_jobs["async-job-1"] = {
            "job_id": "async-job-1",
            "user_id": "default_user",
            "session_id": "session-async",
            "request_id": "async-request-1",
            "status": "pending",
            "result_json": None,
            "error_json": None,
        }
        final_state = ChatExecutionResult(
            session_id="session-async",
            question_type="concept",
            route="explain",
            final_answer="HTTP 是应用层协议。",
            explanation=ExplanationPayload(topic="HTTP"),
            quiz_items=[],
            memory=UserMemoryRecord(),
        )

        async def _run_and_flush_persistence():
            response = await chat_module._run_chat_async_job(
                job_id="async-job-1",
                body=body,
                request_id="async-request-1",
            )
            pending = list(chat_module._RUNNING_CHAT_PERSISTENCE_TASKS)
            if pending:
                await asyncio.gather(*pending)
            return response

        with (
            patch(
                "app.interfaces.api.chat.run_chat_once_with_state",
                return_value=_chat_result_with_state(final_state),
            ) as run_once,
            patch("app.interfaces.api.chat.persist_chat_session", return_value=None),
        ):
            response = asyncio.run(_run_and_flush_persistence())

        self.assertIsNotNone(response)
        self.assertEqual(self.chat_jobs["async-job-1"]["status"], "completed")
        self.assertEqual(self.chat_jobs["async-job-1"]["result_json"]["request_id"], "async-request-1")
        _, kwargs = run_once.call_args
        self.assertEqual(kwargs["request_id"], "async-request-1")

    def test_run_chat_once_uses_orchestrator_runtime_by_default(self) -> None:
        orchestrator_state = {
            "question_type": "concept",
            "route": "explain",
            "explanation": {
                "topic": "HTTP",
                "thinking": "HTTP 是应用层协议。",
                "steps": ["explain_concept"],
                "mistakes": "",
                "similar": [],
            },
            "final_answer": "HTTP 是应用层协议。",
            "quiz_items": [],
            "memory": {},
        }
        with patch("app.application.chat.service.run_orchestrator_chat", return_value=orchestrator_state) as orchestrator:
            result = chat_service.run_chat_once(
                user_id="default_user",
                session_id="session-graph",
                question="什么是 HTTP？",
                subject_id="general",
            )

        self.assertEqual(result.question_type, "concept")
        self.assertEqual(result.explanation.topic, "HTTP")
        self.assertEqual(result.quiz_items, [])
        orchestrator.assert_called_once()
        _, kwargs = orchestrator.call_args
        self.assertEqual(kwargs["request_mode"], "sync")

    def test_orchestrator_chat_state_preserves_structured_explanation(self) -> None:
        state = _chat_state_from_orchestrator_result(
            initial_state={
                "user_id": "default_user",
                "session_id": "session-structured-explanation",
                "question": "什么是 HTTP？",
                "subject_id": "general",
            },
            graph_result={
                "intent_decision": {"intent": "concept_explain", "target_graph_type": "qa"},
                "final_response": {
                    "answer": "HTTP 是应用层协议。",
                    "source_level": "model",
                    "concepts": [{"concept_id": "http", "name": "HTTP", "confidence": 0.8, "source": "test"}],
                    "coach_actions": ["explain_concept"],
                    "ui_payload": {
                        "reasoning_summary": "模型直接回答。",
                        "explanation": {
                            "topic": "HTTP",
                            "thinking": "先讲定位，再讲请求响应。",
                            "steps": ["客户端发送请求。", "服务器返回响应。"],
                            "mistakes": "不要把 HTTP 当成传输层协议。",
                            "similar": ["HTTPS"],
                        },
                    },
                },
            },
            request_mode="sync",
            latency_ms=12,
        )

        self.assertEqual(state["explanation"]["steps"], ["客户端发送请求。", "服务器返回响应。"])
        self.assertNotEqual(state["explanation"]["steps"], ["explain_concept"])

    def test_orchestrator_trace_outputs_include_safe_qa_diagnostics(self) -> None:
        outputs = _trace_outputs(
            {
                "intent_decision": {"intent": "concept_explain", "target_graph_type": "qa"},
                "final_response": {
                    "answer": "HTTP 是应用层协议。",
                    "source_level": "web",
                    "ui_payload": {
                        "reasoning_summary": "安全推理摘要",
                        "selected_model_profile": {"model_id": "deepseek-v4-pro"},
                        "primary_model_id": "deepseek-v4-pro",
                        "fallback_used": True,
                        "fallback_reason": "unauthorized_model",
                        "source_usage": "web",
                        "retrieval_report": {"diagnosis": "web_fallback_used", "doc_count": 1},
                        "web_search_attempted": True,
                    },
                },
                "child_graph_output": {
                    "target_graph_type": "qa",
                    "payload": {
                        "runtime_summary": {
                            "retrieval_diagnosis": {"diagnosis": "web_fallback_used", "raw_count": 1},
                            "tool_calls_count": 1,
                            "tool_decision_rounds_count": 1,
                            "tool_decision_rounds": [
                                {
                                    "round": 1,
                                    "decision": "use_tool",
                                    "tool": "web_search",
                                    "provider": "mcp",
                                    "reason": "按需补充来源。",
                                }
                            ],
                            "fallback_reason": "unauthorized_model",
                        },
                        "tool_results": [
                            {
                                "capability": "web_search",
                                "provider": "mcp",
                                "status": "success",
                            }
                        ],
                        "learning_events": [{}],
                    },
                },
                "errors": [],
            }
        )

        self.assertEqual(outputs["route"], "agent")
        self.assertEqual(outputs["model_name"], "deepseek-v4-pro")
        self.assertEqual(outputs["retrieval_diagnosis"]["diagnosis"], "web_fallback_used")
        self.assertEqual(outputs["tool_decision"]["tool_calls_count"], 1)
        self.assertEqual(outputs["tool_decision"]["capabilities"], ["web_search"])
        self.assertEqual(outputs["fallback_reason"], "unauthorized_model")
        self.assertEqual(outputs["safe_reasoning_summary"], "安全推理摘要")

    def test_run_chat_once_propagates_thinking_mode_to_initial_state(self) -> None:
        orchestrator_state = {
            "question_type": "concept",
            "route": "explain",
            "explanation": {"topic": "HTTP", "thinking": "HTTP 是应用层协议。", "steps": [], "mistakes": "", "similar": []},
            "final_answer": "HTTP 是应用层协议。",
            "quiz_items": [],
            "memory": {},
        }
        with patch("app.application.chat.service.run_orchestrator_chat", return_value=orchestrator_state) as orchestrator:
            chat_service.run_chat_once(
                user_id="default_user",
                session_id="session-thinking",
                question="什么是 HTTP？",
                subject_id="general",
                thinking_mode=True,
            )

        initial_state = orchestrator.call_args.args[0]
        self.assertTrue(initial_state["thinking_mode"])

    def test_run_chat_once_propagates_quiz_clarification_payload(self) -> None:
        quiz_request = {
            "is_quiz_request": True,
            "action": "clarify_quiz_request",
            "intent": "quiz_generation",
            "topic": None,
            "source": "unknown",
            "question_type": "single_choice",
            "difficulty": "adaptive",
            "count": 5,
            "target_module": "practice",
            "need_clarification": True,
            "clarification_reason": "missing_topic",
            "recommended_options": [],
            "custom_input_placeholder": "例如：围绕 HashMap 出 5 道单选题",
            "reason": "quiz_intent_without_usable_topic",
        }
        clarification = {
            "title": "想练哪一块？",
            "description": "我可以帮你生成练习题，但需要先确定练习方向。",
            "recommended_options": [{"label": "输入一个想练的知识点", "value": "custom_topic", "source": "default"}],
            "question_type_options": [],
            "difficulty_options": [],
            "count_options": [],
            "custom_input_placeholder": "例如：围绕 HashMap 出 5 道单选题",
        }
        orchestrator_state = {
            "question_type": "meta",
            "route": "explain",
            "explanation": {},
            "final_answer": "我可以帮你出题，但需要先确定练习方向。",
            "quiz_items": [],
            "quiz_request": quiz_request,
            "quiz_clarification": clarification,
            "memory": {},
        }
        with patch("app.application.chat.service.run_orchestrator_chat", return_value=orchestrator_state):
            result = chat_service.run_chat_once(
                user_id="default_user",
                session_id="session-quiz-clarify",
                question="帮我出点题",
                subject_id="general",
            )

        self.assertEqual(result.quiz_request, QuizRequestResolution.model_validate(quiz_request))
        self.assertEqual(result.quiz_clarification, QuizClarificationPanel.model_validate(clarification))

    def test_run_chat_once_does_not_call_removed_legacy_workflow_or_shadow(self) -> None:
        self.assertFalse(hasattr(chat_service, "run_chat_sync"))
        self.assertFalse(hasattr(chat_service, "run_chat_workflow"))
        self.assertFalse(hasattr(chat_service, "stream_chat_workflow"))
        self.assertFalse(hasattr(chat_service, "schedule_qagraph_shadow"))

    def test_chat_sse_emits_status_and_done(self) -> None:
        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_stream_workflow):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={"user_id": "default_user", "question": "你好", "subject_id": "general"},
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn("event: routing", body)
        self.assertIn("event: explanation", body)
        self.assertIn("event: done", body)
        self.assertIn(json.dumps({"question_type": "smalltalk", "elapsed": 0.01}, ensure_ascii=False), body)
        self.assertIn('{"question_type": "smalltalk", "explanation":', body)

    def test_chat_sse_passes_thinking_mode_to_stream_chat(self) -> None:
        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_stream_workflow) as stream_chat:
            with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "user_id": "default_user",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                    "thinking_mode": True,
                },
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn('"thinking_mode": true', body)
        self.assertTrue(stream_chat.call_args.kwargs["thinking_mode"])

    def test_chat_sse_passes_allow_web_to_stream_chat(self) -> None:
        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_stream_workflow) as stream_chat:
            with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "user_id": "default_user",
                    "question": "联网搜索一下 HTTP/3 现状",
                    "subject_id": "general",
                    "allow_web": True,
                },
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertTrue(stream_chat.call_args.kwargs["allow_web"])

    def test_chat_sse_emits_heartbeat_during_slow_processing(self) -> None:
        with patch.object(chat_module, "CHAT_HEARTBEAT_SECONDS", 0.001):
            with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_stream_with_slow_first_chunk):
                with self.client.stream(
                    "POST",
                    "/api/chat",
                    json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
                ) as response:
                    body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn('"heartbeat": true', body)
        self.assertIn("仍在处理，本轮可能需要更久。", body)
        self.assertIn("event: routing", body)
        self.assertIn("event: done", body)

    def test_stream_chat_uses_orchestrator_runtime_without_shadow_events(self) -> None:
        async def _collect_events():
            chunks = []
            async for chunk in chat_service.stream_chat(
                user_id="default_user",
                session_id="session-1",
                question="你好",
                subject_id="general",
            ):
                chunks.append(chunk)
            return chunks

        stream_chunks = [
            {"node": "router", "state_update": {"question_type": "concept", "route": "explain"}, "elapsed": 0.0},
            {
                "node": "qa_agent_node",
                "state_update": {
                    "question_type": "concept",
                    "route": "explain",
                    "explanation": {
                        "topic": "HTTP",
                        "thinking": "HTTP 是应用层协议。",
                        "steps": ["explain_concept"],
                        "mistakes": "",
                        "similar": [],
                    },
                    "final_answer": "HTTP 是应用层协议。",
                    "streaming_mode": "node",
                },
                "elapsed": 0.01,
            },
            {"node": "memory_node", "state_update": {"memory": {}}, "elapsed": 0.01},
            {
                "node": "finalize_node",
                "state_update": {
                    "finalized": True,
                    "__final_state": {
                        "question_type": "concept",
                        "route": "explain",
                        "explanation": {
                            "topic": "HTTP",
                            "thinking": "HTTP 是应用层协议。",
                            "steps": ["explain_concept"],
                            "mistakes": "",
                            "similar": [],
                        },
                        "final_answer": "HTTP 是应用层协议。",
                        "quiz_items": [],
                        "memory": {},
                        "graph_runtime": {"latency_ms": 12},
                    },
                },
                "elapsed": 0.01,
            },
        ]
        with patch("app.application.chat.service.stream_orchestrator_chat", return_value=iter(stream_chunks)):
            chunks = asyncio.run(_collect_events())

        self.assertEqual([chunk["node"] for chunk in chunks], ["router", "qa_agent_node", "memory_node", "finalize_node"])

    def test_stream_chat_can_emit_answer_delta_before_final_explanation(self) -> None:
        async def _collect_events():
            chunks = []
            async for chunk in chat_service.stream_chat(
                user_id="default_user",
                session_id="session-delta",
                question="什么是 HTTP？",
                subject_id="general",
            ):
                chunks.append(chunk)
            return chunks

        stream_chunks = [
            {"node": "router", "state_update": {"question_type": "concept", "route": "explain"}, "elapsed": 0.0},
            {
                "node": "answer_delta",
                "state_update": {
                    "delta": "HTTP 是",
                    "streaming_mode": "token",
                    "is_synthetic_delta": False,
                },
                "elapsed": 0.01,
            },
            {
                "node": "answer_delta",
                "state_update": {
                    "delta": "应用层协议。",
                    "streaming_mode": "token",
                    "is_synthetic_delta": False,
                },
                "elapsed": 0.02,
            },
            {
                "node": "qa_agent_node",
                "state_update": {"final_answer": "HTTP 是应用层协议。", "streaming_mode": "token"},
                "elapsed": 0.03,
            },
            {
                "node": "finalize_node",
                "state_update": {
                    "finalized": True,
                    "__final_state": {
                        "question_type": "concept",
                        "route": "explain",
                        "explanation": {},
                        "final_answer": "HTTP 是应用层协议。",
                        "quiz_items": [],
                        "memory": {},
                    },
                },
                "elapsed": 0.03,
            },
        ]
        with patch("app.application.chat.service.stream_orchestrator_chat", return_value=iter(stream_chunks)):
            chunks = asyncio.run(_collect_events())

        self.assertEqual([chunk["node"] for chunk in chunks[:3]], ["router", "answer_delta", "answer_delta"])
        self.assertEqual(chunks[1]["state_update"]["streaming_mode"], "token")
        self.assertFalse(chunks[1]["state_update"]["is_synthetic_delta"])

    def test_stream_chat_buffers_answer_until_quality_gated_final_chunk(self) -> None:
        async def _collect_events():
            chunks = []
            async for chunk in chat_service.stream_chat(
                user_id="default_user",
                session_id="session-buffered-stream",
                question="什么是 HTTP？",
                subject_id="general",
            ):
                chunks.append(chunk)
            return chunks

        stream_chunks = [
            {"node": "stream_status", "state_update": {"stream_stage": "evidence_merge"}, "elapsed": 0.01},
            {
                "node": "qa_agent_node",
                "state_update": {"final_answer": "HTTP 是应用层协议。", "streaming_mode": "node"},
                "elapsed": 0.02,
            },
            {
                "node": "finalize_node",
                "state_update": {
                    "finalized": True,
                    "__final_state": {
                        "question_type": "concept",
                        "route": "explain",
                        "explanation": {},
                        "final_answer": "HTTP 是应用层协议。",
                        "quiz_items": [],
                        "memory": {},
                    },
                },
                "elapsed": 0.03,
            },
            {
                "node": "final",
                "state_update": {
                    "finalized": True,
                    "__final_state": {
                        "question_type": "concept",
                        "route": "explain",
                        "explanation": {},
                        "final_answer": "HTTP 是应用层协议。",
                        "quiz_items": [],
                        "memory": {},
                    },
                },
                "elapsed": 0.03,
            },
        ]
        with patch("app.application.chat.service.stream_orchestrator_chat", return_value=iter(stream_chunks)):
            chunks = asyncio.run(_collect_events())

        delta_chunks = [chunk for chunk in chunks if chunk["node"] == "answer_delta"]
        self.assertFalse([chunk for chunk in delta_chunks if not chunk["state_update"].get("is_synthetic_delta")])
        self.assertIn("qa_agent_node", [chunk["node"] for chunk in chunks])
        self.assertEqual(chunks[-1]["node"], "final")

    def test_chat_sse_emits_reasoning_delta_and_real_answer_delta(self) -> None:
        async def _fake_token_stream(**_kwargs):
            yield {
                "node": "stream_status",
                "state_update": {
                    "stream_stage": "reasoning_stream",
                    "stage_label": "模型思考",
                    "detail": "正在接收模型思考过程。",
                    "safe_decision_summary": "调试信息仅本轮展示，不进入回答正文、历史或 LangSmith。",
                    "status": "running",
                    "streaming_mode": "token",
                },
                "elapsed": 0.01,
            }
            yield {
                "node": "reasoning_delta",
                "state_update": {
                    "delta": "先判断 HTTP 的协议层级。",
                    "streaming_mode": "token",
                    "source": "deepseek_reasoning_content",
                    "ephemeral": True,
                },
                "elapsed": 0.015,
            }
            yield {
                "node": "answer_delta",
                "state_update": {
                    "delta": "HTTP 是",
                    "streaming_mode": "token",
                    "is_synthetic_delta": False,
                },
                "elapsed": 0.02,
            }
            yield {
                "node": "qa_agent_node",
                "state_update": {
                    "final_answer": "HTTP 是应用层协议。",
                    "streaming_mode": "token",
                    "reasoning_summary": "安全决策摘要",
                },
                "elapsed": 0.03,
            }

        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_token_stream):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "user_id": "default_user",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                    "thinking_mode": True,
                },
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn('"safe_decision_summary": "调试信息仅本轮展示，不进入回答正文、历史或 LangSmith。"', body)
        self.assertIn("event: reasoning_delta", body)
        self.assertIn('"source": "deepseek_reasoning_content"', body)
        self.assertIn('"ephemeral": true', body)
        self.assertIn("event: answer_delta", body)
        self.assertIn('"streaming_mode": "token"', body)
        self.assertIn('"is_synthetic_delta": false', body)
        self.assertNotIn("hidden_reasoning", body)

    def test_chat_sse_forwards_runtime_writer_token_before_graph_answer(self) -> None:
        def _fake_stream_orchestrator(initial_state, **_kwargs):
            return _RuntimeWriterTokenIterator(initial_state)

        with (
            patch("app.application.chat.service.stream_orchestrator_chat", side_effect=_fake_stream_orchestrator),
            patch.object(chat_module, "CHAT_HEARTBEAT_SECONDS", 0.01),
        ):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "user_id": "default_user",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: answer_delta", body)
        self.assertIn('"delta": "HTTP 是"', body)
        self.assertIn('"streaming_mode": "token"', body)
        self.assertIn('"is_synthetic_delta": false', body)
        self.assertLess(body.index("event: answer_delta"), body.index("event: explanation"))

    def test_chat_sse_forwards_real_qagraph_token_before_graph_answer(self) -> None:
        initial_state = {
            "user_id": "default_user",
            "session_id": "session-real-qagraph-token",
            "subject_id": "general",
            "subject_name": "数据结构与算法",
            "subject_description": "",
            "question": "什么是 HTTP？",
            "request_mode": "sse",
            "thinking_mode": False,
            "memory": {},
            "short_term_messages": [],
            "short_term_context": "",
            "session_memory": {},
            "session_memory_context": "",
            "long_term_context": "",
            "model_name": "deepseek-v4-pro",
            "evidence": [
                {
                    "id": "http-notebook-evidence",
                    "source_type": "notebook",
                    "source_id": "general:http",
                    "text": "HTTP 是一种应用层协议，用于客户端和服务器之间传输超文本资源。",
                    "score": 0.95,
                }
            ],
        }
        fake_llm = _FakeStreamingLLM(["HTTP 是", "应用层协议。"])

        with (
            patch("app.application.chat.service.build_initial_state", return_value=dict(initial_state)),
            patch("app.application.chat.service.persist_chat_session"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
            patch.object(chat_module, "CHAT_HEARTBEAT_SECONDS", 0.01),
        ):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "user_id": "default_user",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: answer_delta", body)
        self.assertIn('"delta": "HTTP 是"', body)
        self.assertIn('"delta": "应用层协议。"', body)
        self.assertIn('"streaming_mode": "token"', body)
        self.assertIn('"is_synthetic_delta": false', body)
        self.assertLess(body.index('"delta": "HTTP 是"'), body.index("event: explanation"))

    def test_chat_sse_emits_final_event_before_done(self) -> None:
        async def _fake_final_stream(**_kwargs):
            yield {
                "node": "stream_status",
                "state_update": {
                    "stream_stage": "request_guard",
                    "stage_label": "请求检查",
                    "detail": "正在检查请求是否合法。",
                    "status": "done",
                    "streaming_mode": "node",
                },
                "elapsed": 0.01,
            }
            yield {
                "node": "qa_agent_node",
                "state_update": {
                    "question_type": "concept",
                    "route": "explain",
                    "final_answer": "HTTP 是应用层协议。",
                    "streaming_mode": "node",
                },
                "elapsed": 0.02,
            }
            yield {
                "node": "final",
                "state_update": {
                    "finalized": True,
                    "question_type": "concept",
                    "route": "explain",
                    "final_answer": "HTTP 是应用层协议。",
                },
                "elapsed": 0.03,
            }

        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_final_stream):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn("event: explanation", body)
        self.assertIn("event: final", body)
        self.assertIn("event: done", body)
        self.assertLess(body.index("event: status"), body.index("event: explanation"))
        self.assertLess(body.index("event: explanation"), body.index("event: final"))
        self.assertLess(body.index("event: final"), body.index("event: done"))

    def test_chat_sse_emits_readable_error_and_closes_on_exception(self) -> None:
        with patch("app.interfaces.api.chat.stream_chat", side_effect=_fake_stream_failure):
            with self.client.stream(
                "POST",
                "/api/chat",
                json={"user_id": "default_user", "question": "你好", "subject_id": "general"},
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn("event: error", body)
        self.assertIn('"error": "当前模型服务暂时不可用，我没有拿到稳定回答。请稍后重试，或切换模型后再问。"', body)
        self.assertIn('"error_type": "model_unavailable"', body)
        self.assertIn('"reason": "model_unavailable"', body)
        self.assertIn('"retryable": true', body)
        error_payload = next(
            json.loads(line.removeprefix("data: "))
            for line in body.splitlines()
            if line.startswith("data: ") and '"error_type"' in line
        )
        encoded_error = json.dumps(
            {
                "error": error_payload.get("error"),
                "error_type": error_payload.get("error_type"),
                "reason": error_payload.get("reason"),
            },
            ensure_ascii=False,
        )
        self.assertNotIn("401", encoded_error)
        self.assertNotIn("RuntimeError", encoded_error)
        self.assertNotIn("subscription tier", encoded_error)

    def test_sse_cleanup_awaits_cancelled_pending_chunk_before_close(self) -> None:
        async def _run_cleanup() -> _CloseGuardedStream:
            pending_task = asyncio.create_task(asyncio.sleep(10))
            stream = _CloseGuardedStream(pending_task)
            await chat_module._close_chat_stream_safely(
                chat_stream=stream,
                pending_chunk_task=pending_task,
            )
            self.assertTrue(pending_task.cancelled())
            return stream

        stream = asyncio.run(_run_cleanup())
        self.assertTrue(stream.closed)

    def test_initial_state_contains_short_and_long_term_context(self) -> None:
        request = ChatRequest(
            user_id="default_user",
            session_id="session-1",
            question="那为什么会这样？",
            subject_id="general",
            client_request_id="client-turn-1",
        )

        state = chat_state_builder.build_initial_state(
            user_id=request.user_id,
            session_id=request.session_id,
            question=request.question,
            subject_id=request.subject_id,
            request_mode="sync",
            client_request_id=request.client_request_id,
        )

        self.assertEqual(state["message_id"], "client-turn-1")
        self.assertEqual(state["request_id"], "client-turn-1")
        self.assertEqual(state["client_request_id"], "client-turn-1")
        self.assertEqual(len(state["short_term_messages"]), 2)
        self.assertEqual(state["request_mode"], "sync")
        self.assertEqual(state["subject_id"], "data-structure")
        self.assertIn("助手2（主题：HTTP）", state["short_term_context"])
        self.assertEqual(state["session_memory"]["active_topic"], "HTTP")
        self.assertIn("当前主主题：HTTP", state["session_memory_context"])
        self.assertIn("用户昵称：测试用户", state["long_term_context"])

    def test_initial_state_marks_client_requested_web_search(self) -> None:
        state = chat_state_builder.build_initial_state(
            user_id="default_user",
            session_id="session-web",
            question="什么是 HTTP？",
            subject_id="general",
            request_mode="sync",
            allow_web=True,
        )

        self.assertTrue(state["allow_web"])
        self.assertTrue(state["web_search_requested"])
        self.assertEqual(state["source_policy"], "notebook_plus_external")

    def test_initial_state_generates_distinct_message_ids_without_client_request_id(self) -> None:
        first = chat_state_builder.build_initial_state(
            user_id="default_user",
            session_id="session-1",
            question="什么是 HTTP？",
            subject_id="general",
            request_mode="sync",
        )
        second = chat_state_builder.build_initial_state(
            user_id="default_user",
            session_id="session-1",
            question="什么是 HTTP？",
            subject_id="general",
            request_mode="sync",
        )

        self.assertTrue(first["message_id"])
        self.assertTrue(second["message_id"])
        self.assertNotEqual(first["message_id"], second["message_id"])

    def test_initial_state_uses_backend_request_id_without_client_request_id(self) -> None:
        state = chat_state_builder.build_initial_state(
            user_id="default_user",
            session_id="session-1",
            question="什么是 HTTP？",
            subject_id="general",
            request_mode="sync",
            request_id="server-request-1",
        )

        self.assertEqual(state["message_id"], "server-request-1")
        self.assertEqual(state["request_id"], "server-request-1")
        self.assertEqual(state["client_request_id"], "")

    def test_build_assistant_message_includes_process_with_tool_calls(self) -> None:
        final_state = {
            "question_type": "practice",
            "is_rewritten": True,
            "retrieved_docs": [{"score": 0.91}, {"score": 0.83}],
            "execution_mode": "tool_calling",
            "degraded": False,
            "selected_model_profile": {
                "model_id": "glm-5",
                "family": "GLM",
                "provider": "zhipu",
            },
            "tool_calls": [
                {
                    "name": "notebook_retrieve",
                    "capability": "notebook_retrieve",
                    "success": True,
                    "doc_count": 2,
                },
                {
                    "name": "question_recommend",
                    "capability": "question_recommend",
                    "success": False,
                    "error": "timeout",
                },
            ],
            "explanation": {
                "topic": "HTTP",
                "thinking": "先确认题型，再结合上下文检索与练习目标组织回答。",
                "steps": ["解释缓存语义", "补两道练习题"],
                "mistakes": "不要把 HTTP 误认为传输层协议",
                "similar": [],
            },
            "final_answer": "HTTP 是一种无状态的应用层协议。",
            "quiz_items": [{"question": "示例题"}],
        }

        message = chat_messages.build_assistant_message(final_state, include_process=True)

        self.assertEqual(message["content"], "HTTP 是一种无状态的应用层协议。")
        self.assertEqual(message["questionType"], "practice")
        self.assertIn("process", message)
        process = message["process"]
        self.assertEqual(process["currentStage"], "练习题已准备")
        self.assertEqual(
            [stage["key"] for stage in process["stages"]],
            ["routing", "retrieval", "execution", "answer"],
        )
        self.assertEqual(process["stages"][0]["detail"], "已识别为练习出题。")
        self.assertEqual(
            process["stages"][1]["detail"],
            "知识检索命中 2 条内容，并自动改写了查询。",
        )
        self.assertEqual(process["execution"]["mode"], "工具调用")
        self.assertEqual(process["execution"]["modelId"], "glm-5")
        self.assertEqual(process["toolCalls"][0]["label"], "搜索笔记本")
        self.assertEqual(process["toolCalls"][0]["argsSummary"], "无额外参数")
        self.assertFalse(process["toolCalls"][1]["success"])
        self.assertEqual(process["toolCalls"][1]["error"], "timeout")
        self.assertEqual(
            process["reasoningSummary"],
            "先确认题型，再结合上下文检索与练习目标组织回答。",
        )

    def test_build_assistant_message_hides_process_by_default(self) -> None:
        message = chat_messages.build_assistant_message(
            {
                "question_type": "concept",
                "route": "explain",
                "final_answer": "HTTP 是应用层协议。",
                "explanation": {"topic": "HTTP", "thinking": "内部推理摘要。"},
            }
        )

        self.assertNotIn("process", message)

    def test_build_assistant_message_without_tools_uses_summary_content(self) -> None:
        final_state = {
            "question_type": "meta",
            "explanation": {
                "topic": "当前模型",
                "thinking": "我先读取配置，再把模型信息整理成用户可读的说明。",
                "steps": ["读取当前配置", "整理输出"],
                "mistakes": [],
                "similar": [],
            },
        }

        message = chat_messages.build_assistant_message(final_state, include_process=True)

        self.assertEqual(message["content"], "我已经围绕「当前模型」整理好讲解了。")
        self.assertIn("process", message)
        process = message["process"]
        self.assertEqual(process["currentStage"], "已生成回答")
        self.assertEqual([stage["key"] for stage in process["stages"]], ["routing", "answer"])
        self.assertEqual(process["toolCalls"], [])
        self.assertEqual(
            process["reasoningSummary"],
            "我先读取配置，再把模型信息整理成用户可读的说明。",
        )


if __name__ == "__main__":
    unittest.main()
