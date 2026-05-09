from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
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
from app.application.chat.orchestrator_runtime import _chat_state_from_orchestrator_result
from app.application.chat import service as chat_service
from app.application.chat import state_builder as chat_state_builder
from app.interfaces.auth.dependencies import require_current_user
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
    raise RuntimeError()
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


class ChatApiTest(unittest.TestCase):
    def setUp(self) -> None:
        AppStatus.should_exit_event = None
        app = FastAPI()
        app.include_router(chat_router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: AuthUserView(
            id="default_user",
            email="default@example.com",
            display_name="测试用户",
            status="active",
        )
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
        with patch("app.interfaces.api.chat.run_chat_sync", return_value=final_state):
            response = self.client.post(
                "/api/chat/sync",
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["question_type"], "concept")
        self.assertEqual(payload["explanation"]["topic"], "HTTP")

    def test_run_chat_sync_uses_orchestrator_runtime_by_default(self) -> None:
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
            result = chat_service.run_chat_sync(
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

    def test_run_chat_sync_propagates_thinking_mode_to_initial_state(self) -> None:
        orchestrator_state = {
            "question_type": "concept",
            "route": "explain",
            "explanation": {"topic": "HTTP", "thinking": "HTTP 是应用层协议。", "steps": [], "mistakes": "", "similar": []},
            "final_answer": "HTTP 是应用层协议。",
            "quiz_items": [],
            "memory": {},
        }
        with patch("app.application.chat.service.run_orchestrator_chat", return_value=orchestrator_state) as orchestrator:
            chat_service.run_chat_sync(
                user_id="default_user",
                session_id="session-thinking",
                question="什么是 HTTP？",
                subject_id="general",
                thinking_mode=True,
            )

        initial_state = orchestrator.call_args.args[0]
        self.assertTrue(initial_state["thinking_mode"])

    def test_run_chat_sync_propagates_quiz_clarification_payload(self) -> None:
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
            result = chat_service.run_chat_sync(
                user_id="default_user",
                session_id="session-quiz-clarify",
                question="帮我出点题",
                subject_id="general",
            )

        self.assertEqual(result.quiz_request, QuizRequestResolution.model_validate(quiz_request))
        self.assertEqual(result.quiz_clarification, QuizClarificationPanel.model_validate(clarification))

    def test_run_chat_sync_does_not_call_removed_legacy_workflow_or_shadow(self) -> None:
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

    def test_stream_chat_deterministic_context_emits_real_token_delta(self) -> None:
        async def _collect_events():
            chunks = []
            async for chunk in chat_service.stream_chat(
                user_id="default_user",
                session_id="session-deterministic-stream",
                question="什么是 HTTP？",
                subject_id="general",
            ):
                chunks.append(chunk)
            return chunks

        fake_llm = _FakeStreamingLLM(["HTTP 是", "应用层协议。"])
        with (
            patch("app.application.chat.orchestrator_runtime.is_graph_facts_enabled", return_value=False),
            patch("app.persistence.repositories.graph_facts.is_graph_facts_enabled", return_value=False),
            patch("app.domains.qa.runtime.select_execution_mode", return_value="deterministic_context"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
        ):
            chunks = asyncio.run(_collect_events())

        delta_chunks = [chunk for chunk in chunks if chunk["node"] == "answer_delta"]
        self.assertGreaterEqual(len(delta_chunks), 2)
        self.assertEqual(delta_chunks[0]["state_update"]["streaming_mode"], "token")
        self.assertFalse(delta_chunks[0]["state_update"]["is_synthetic_delta"])
        self.assertIn("qa_agent_node", [chunk["node"] for chunk in chunks])

    def test_chat_sse_emits_safe_stream_status_and_real_answer_delta(self) -> None:
        async def _fake_token_stream(**_kwargs):
            yield {
                "node": "stream_status",
                "state_update": {
                    "stream_stage": "model_start",
                    "stage_label": "模型执行",
                    "detail": "模型已开始生成回答。",
                    "safe_decision_summary": "本轮直接回答，不展示原始隐藏思维链。",
                    "status": "running",
                    "streaming_mode": "token",
                },
                "elapsed": 0.01,
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
                json={"user_id": "default_user", "question": "什么是 HTTP？", "subject_id": "general"},
            ) as response:
                body = "".join(chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status", body)
        self.assertIn('"safe_decision_summary": "本轮直接回答，不展示原始隐藏思维链。"', body)
        self.assertIn("event: answer_delta", body)
        self.assertIn('"streaming_mode": "token"', body)
        self.assertIn('"is_synthetic_delta": false', body)
        self.assertNotIn("hidden_reasoning", body)

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
        self.assertIn('"error": "学习引擎处理失败（RuntimeError），请稍后重试。"', body)
        self.assertIn('"error_type": "RuntimeError"', body)
        self.assertIn('"reason": "workflow_error"', body)
        self.assertIn('"retryable": true', body)

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
        )

        state = chat_state_builder.build_initial_state(
            user_id=request.user_id,
            session_id=request.session_id,
            question=request.question,
            subject_id=request.subject_id,
            request_mode="sync",
        )

        self.assertEqual(len(state["short_term_messages"]), 2)
        self.assertEqual(state["request_mode"], "sync")
        self.assertEqual(state["subject_id"], "data-structure")
        self.assertIn("助手2（主题：HTTP）", state["short_term_context"])
        self.assertEqual(state["session_memory"]["active_topic"], "HTTP")
        self.assertIn("当前主主题：HTTP", state["session_memory_context"])
        self.assertIn("用户昵称：测试用户", state["long_term_context"])

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

        message = chat_messages.build_assistant_message(final_state)

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

        message = chat_messages.build_assistant_message(final_state)

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
