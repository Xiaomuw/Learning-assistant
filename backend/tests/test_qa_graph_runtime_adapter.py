from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.qa.runtime import _stream_delta_to_text, _stream_reasoning_delta_to_text, create_agent
from app.domains.qa.schemas import AgentExecutionResult, AgentRequest, AnswerSchema
from app.orchestration.graphs.qa.adapter import ProductionQARuntimeAdapter
from app.orchestration.graphs.qa.graph import build_graph
from app.shared.schemas.agent_graphs import FinalResponse, SourceLevel, SourcePolicy, ToolCapability, ToolStatus
from app.shared.schemas.model_profile import ModelProfile


def _profile() -> ModelProfile:
    return ModelProfile(
        model_id="test-model",
        provider="test",
        family="TEST",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=8000,
    )


class _FakeAgent:
    def __init__(self, result: AgentExecutionResult) -> None:
        self._result = result

    def run(self) -> AgentExecutionResult:
        return self._result


class _FakeStreamChunk:
    def __init__(
        self,
        content,
        *,
        additional_kwargs: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.additional_kwargs = additional_kwargs or {}
        self.response_metadata = response_metadata or {}


class _FakeStreamingLLM:
    def __init__(self, chunks: list[Any] | None = None, invoke_text: str = "HTTP 是应用层协议。") -> None:
        self.chunks = list(chunks or [])
        self.invoke_text = invoke_text

    def stream(self, _messages):
        for chunk in self.chunks:
            if hasattr(chunk, "content"):
                yield chunk
            else:
                yield _FakeStreamChunk(chunk)

    def invoke(self, _messages):
        return self.invoke_text


def _runtime_request(runtime_context: dict | None = None) -> AgentRequest:
    return AgentRequest(
        user_id="u1",
        session_id="s1",
        subject_id="general",
        subject_name="通用知识库",
        subject_description="用于概念问答。",
        question="什么是 HTTP？",
        question_type="concept",
        short_term_context="学生1: 什么是 HTTP？",
        session_memory_context="当前主主题：HTTP",
        long_term_context="用户昵称：测试用户",
        runtime_context=dict(runtime_context or {}),
        model_name="test-model",
    )


class QAGraphRuntimeAdapterTest(unittest.TestCase):
    def _invoke_with_runtime_result(
        self,
        runtime_result: AgentExecutionResult,
        *,
        question: str = "HTTP/3 现在浏览器支持怎么样？",
    ) -> dict:
        adapter = ProductionQARuntimeAdapter(
            model_name="test-model",
            user_id="u1",
            session_id="s1",
            subject_id="general",
            allow_tools=True,
            allow_search=True,
        )
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=_profile()),
            patch("app.orchestration.graphs.qa.adapter.create_agent", return_value=_FakeAgent(runtime_result)),
        ):
            return build_graph(adapter=adapter).compile().invoke(
                {
                    "run_id": "run-production-runtime",
                    "user_id": "u1",
                    "thread_id": "s1",
                    "user_message": question,
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            )

    def test_runtime_web_evidence_stays_diagnostic_without_graph_judge(self) -> None:
        result = self._invoke_with_runtime_result(
            AgentExecutionResult(
                execution_mode="tool_calling",
                answer=AnswerSchema(
                    topic="HTTP/3",
                    thinking="HTTP/3 支持情况需要参考浏览器资料。",
                    steps=["总结主流浏览器支持情况"],
                    similar=["QUIC", "TLS"],
                    final_answer="HTTP/3 已被主流现代浏览器支持，但具体版本要看官方兼容表。",
                ),
                retrieved_docs=[
                    {
                        "doc_id": "web-http3",
                        "content": "Chrome、Firefox、Safari 已支持 HTTP/3。",
                        "metadata": {"retrieval_source": "tavily_web", "url": "https://example.com/http3"},
                        "score": 0.92,
                    }
                ],
                tool_calls=[
                    {
                        "name": "web_search",
                        "capability": ToolCapability.WEB_SEARCH.value,
                        "provider": "tavily",
                        "success": True,
                        "doc_count": 1,
                        "is_external": True,
                    }
                ],
                tool_decision_rounds=[
                    {
                        "round": 1,
                        "decision": "use_tool",
                        "tool": ToolCapability.WEB_SEARCH.value,
                        "provider": "tavily",
                        "reason": "按需补充最新来源。",
                    }
                ],
                retrieval_diagnosis={"diagnosis": "web_search_used", "raw_count": 1},
                source_usage="web",
                final_answer="HTTP/3 已被主流现代浏览器支持，但具体版本要看官方兼容表。",
                selected_model_profile={"model_id": "test-model"},
            )
        )

        response = FinalResponse.model_validate(result["final_response"])
        tool_result = result["tool_results"][0]
        event_types = {item["event_type"] for item in result["learning_events"]}

        self.assertEqual(response.source_level, SourceLevel.MODEL)
        self.assertEqual(response.evidence_refs, [])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(tool_result["provider"], "tavily")
        self.assertEqual(tool_result["capability"], ToolCapability.WEB_SEARCH.value)
        self.assertEqual(tool_result["status"], ToolStatus.SUCCESS.value)
        self.assertEqual(tool_result["evidence"][0]["source_type"], "web")
        self.assertEqual(response.ui_payload["explanation"]["topic"], "HTTP/3")
        self.assertEqual(response.ui_payload["explanation"]["steps"], ["总结主流浏览器支持情况"])
        self.assertNotIn("raw_output", response.ui_payload)
        self.assertEqual(result["runtime_summary"]["retrieval_diagnosis"]["diagnosis"], "web_search_used")
        self.assertEqual(result["runtime_summary"]["tool_decision_rounds"][0]["tool"], ToolCapability.WEB_SEARCH.value)
        self.assertIn("tool_fallback_used", event_types)
        self.assertIn("question_answered", event_types)

    def test_maps_tavily_failure_to_tool_result_and_graph_error(self) -> None:
        result = self._invoke_with_runtime_result(
            AgentExecutionResult(
                execution_mode="tool_calling",
                answer=AnswerSchema(
                    topic="HTTP/3",
                    thinking="搜索失败后先给稳定背景。",
                    steps=["HTTP/3 基于 QUIC"],
                    similar=["HTTP/2", "QUIC"],
                    final_answer="我现在不能确认最新支持表，但 HTTP/3 基于 QUIC。",
                ),
                tool_calls=[
                    {
                        "name": "web_search",
                        "capability": ToolCapability.WEB_SEARCH.value,
                        "provider": "tavily",
                        "success": False,
                        "error": "tavily unauthorized",
                        "is_external": True,
                    }
                ],
                source_usage="model",
                final_answer="我现在不能确认最新支持表，但 HTTP/3 基于 QUIC。",
            )
        )

        self.assertEqual(result["tool_results"][0]["status"], ToolStatus.ERROR.value)
        self.assertEqual(result["tool_results"][0]["provider"], "tavily")
        self.assertEqual(result["errors"][0]["code"], "tool_call_failed")
        self.assertEqual(result["errors"][0]["metadata"]["provider"], "tavily")

    def test_maps_tool_timeout_to_timeout_status(self) -> None:
        result = self._invoke_with_runtime_result(
            AgentExecutionResult(
                execution_mode="tool_calling",
                answer=AnswerSchema(
                    topic="HTTP",
                    thinking="工具超时后直接回答稳定概念。",
                    steps=["HTTP 是应用层协议"],
                    similar=["HTTPS", "TCP"],
                    final_answer="HTTP 是应用层协议。",
                ),
                tool_calls=[
                    {
                        "name": "web_search",
                        "capability": ToolCapability.WEB_SEARCH.value,
                        "provider": "mcp",
                        "success": False,
                        "error": "timeout",
                        "is_external": True,
                    }
                ],
                final_answer="HTTP 是应用层协议。",
            )
        )

        self.assertEqual(result["tool_results"][0]["status"], ToolStatus.TIMEOUT.value)
        self.assertEqual(result["errors"][0]["code"], "tool_timeout")

    def test_maps_model_degraded_to_warning_and_learning_event(self) -> None:
        result = self._invoke_with_runtime_result(
            AgentExecutionResult(
                execution_mode="deterministic_context",
                answer=AnswerSchema(
                    topic="HTTP",
                    thinking="使用确定性 fallback 生成简版回答。",
                    steps=["HTTP 是请求响应协议"],
                    similar=["HTTPS", "TCP"],
                    final_answer="HTTP 是请求响应式应用层协议。",
                ),
                degraded=True,
                primary_model_id="llama3.3-70b-instruct",
                fallback_model_id="qwen3-coder-flash",
                fallback_used=True,
                fallback_reason="unauthorized_model",
                model_attempts=[
                    {"model_id": "llama3.3-70b-instruct", "role": "primary", "status": "failed"},
                    {"model_id": "qwen3-coder-flash", "role": "fallback", "status": "ok"},
                ],
                final_answer="HTTP 是请求响应式应用层协议。",
            ),
            question="什么是 HTTP？",
        )

        event_types = {item["event_type"] for item in result["learning_events"]}
        self.assertIn("qa_runtime_degraded", {item["code"] for item in result["errors"]})
        self.assertIn("answer_repaired", event_types)
        self.assertTrue(result["final_response"]["ui_payload"]["degraded"])
        self.assertTrue(result["final_response"]["ui_payload"]["fallback_used"])
        self.assertEqual(result["final_response"]["ui_payload"]["primary_model_id"], "llama3.3-70b-instruct")
        self.assertEqual(result["final_response"]["ui_payload"]["fallback_model_id"], "qwen3-coder-flash")

    def test_deterministic_context_streams_plaintext_tokens_when_available(self) -> None:
        request = _runtime_request({"stream_answer_tokens": True})
        fake_llm = _FakeStreamingLLM(["HTTP 是", "应用层协议。"])

        with (
            patch("app.domains.qa.runtime.select_execution_mode", return_value="deterministic_context"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
        ):
            result = create_agent(request, state={}, model_profile=_profile()).run()

        self.assertEqual(result.execution_mode, "deterministic_context")
        self.assertEqual(result.streaming_mode, "token")
        self.assertEqual(result.streaming_token_count, 2)
        self.assertFalse(result.streaming_degraded_reason)
        self.assertEqual(result.final_answer, "HTTP 是应用层协议。")

    def test_deterministic_context_empty_stream_degrades_to_node_streaming(self) -> None:
        request = _runtime_request({"stream_answer_tokens": True})
        fake_llm = _FakeStreamingLLM([], invoke_text="HTTP fallback answer")

        with (
            patch("app.domains.qa.runtime.select_execution_mode", return_value="deterministic_context"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
        ):
            result = create_agent(request, state={}, model_profile=_profile()).run()

        self.assertEqual(result.execution_mode, "deterministic_context")
        self.assertEqual(result.streaming_mode, "node")
        self.assertEqual(result.streaming_token_count, 0)
        self.assertEqual(result.streaming_degraded_reason, "provider_stream_returned_no_chunks")
        self.assertEqual(result.final_answer, "HTTP fallback answer")

    def test_stream_delta_filters_reasoning_content_blocks(self) -> None:
        chunk = _FakeStreamChunk(
            [
                {"type": "reasoning", "text": "hidden chain"},
                {"type": "thinking", "content": "hidden thought"},
                {"type": "text", "text": "visible answer"},
            ]
        )

        self.assertEqual(_stream_delta_to_text(chunk), "visible answer")

    def test_reasoning_delta_extracts_debug_content_from_deepseek_chunks(self) -> None:
        chunk = _FakeStreamChunk(
            [
                {"type": "reasoning_content", "text": "先判断协议层。"},
                {"type": "text", "text": "visible answer"},
            ],
            additional_kwargs={"reasoning_content": "模型先分析题意。"},
            response_metadata={"reasoning_content": "再确认概念边界。"},
        )

        self.assertEqual(_stream_delta_to_text(chunk), "visible answer")
        self.assertEqual(
            _stream_reasoning_delta_to_text(chunk),
            "模型先分析题意。再确认概念边界。先判断协议层。",
        )

    def test_deterministic_context_streams_reasoning_delta_only_in_thinking_mode(self) -> None:
        events: list[dict[str, Any]] = []
        request = _runtime_request(
            {
                "stream_answer_tokens": True,
                "thinking_mode": True,
                "stream_writer": lambda event: events.append(event),
            }
        )
        fake_llm = _FakeStreamingLLM(
            [
                _FakeStreamChunk(
                    "HTTP 是",
                    additional_kwargs={"reasoning_content": "先判断 HTTP 所在层级。"},
                ),
                _FakeStreamChunk(
                    [
                        {"type": "reasoning_content", "text": "再确认它不是传输层协议。"},
                        {"type": "text", "text": "应用层协议。"},
                    ]
                ),
            ]
        )

        with (
            patch("app.domains.qa.runtime.select_execution_mode", return_value="deterministic_context"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
        ):
            result = create_agent(request, state={}, model_profile=_profile()).run()

        reasoning_events = [event for event in events if event.get("event") == "reasoning_delta"]
        answer_events = [event for event in events if event.get("event") == "answer_delta"]
        self.assertEqual(result.final_answer, "HTTP 是应用层协议。")
        self.assertEqual(len(reasoning_events), 2)
        self.assertEqual(len(answer_events), 2)
        self.assertTrue(reasoning_events[0]["data"]["ephemeral"])
        self.assertNotIn("先判断", result.final_answer)
        self.assertGreater(request.runtime_context["reasoning_trace_char_count"], 0)

    def test_reasoning_delta_not_emitted_when_thinking_mode_disabled(self) -> None:
        events: list[dict[str, Any]] = []
        request = _runtime_request(
            {
                "stream_answer_tokens": True,
                "thinking_mode": False,
                "stream_writer": lambda event: events.append(event),
            }
        )
        fake_llm = _FakeStreamingLLM(
            [
                _FakeStreamChunk(
                    "HTTP 是应用层协议。",
                    additional_kwargs={"reasoning_content": "不应输出的思考过程。"},
                ),
            ]
        )

        with (
            patch("app.domains.qa.runtime.select_execution_mode", return_value="deterministic_context"),
            patch("app.domains.qa.runtime.get_chat_llm", return_value=fake_llm),
        ):
            result = create_agent(request, state={}, model_profile=_profile()).run()

        self.assertEqual(result.final_answer, "HTTP 是应用层协议。")
        self.assertFalse([event for event in events if event.get("event") == "reasoning_delta"])
        self.assertEqual([event.get("event") for event in events if event.get("event") == "answer_delta"], ["answer_delta"])

    def test_maps_empty_answer_to_safe_contract_error(self) -> None:
        result = self._invoke_with_runtime_result(
            AgentExecutionResult(
                execution_mode="structured_output",
                raw_output="",
                final_answer="",
            )
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertIn("缺少足够可靠的证据", response.answer)
        self.assertEqual(response.ui_payload["answer_mode"], "clarification_required")
        self.assertIn("empty_answer", {item["code"] for item in result["errors"]})

    def test_runtime_exception_returns_safe_contract_error(self) -> None:
        adapter = ProductionQARuntimeAdapter(model_name="test-model", user_id="u1")
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=_profile()),
            patch("app.orchestration.graphs.qa.adapter.create_agent", side_effect=RuntimeError("boom")),
        ):
            result = build_graph(adapter=adapter).compile().invoke(
                {
                    "run_id": "run-error",
                    "user_id": "u1",
                    "user_message": "什么是 HTTP？",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            )

        self.assertEqual(result["errors"][0]["code"], "production_qa_runtime_error")
        self.assertIn("暂时不可用", result["final_response"]["answer"])

    def test_stable_concept_with_default_notebook_uses_concept_filtered_retrieval(self) -> None:
        runtime_result = AgentExecutionResult(
            execution_mode="deterministic_context",
            answer=AnswerSchema(
                topic="HTTP",
                thinking="HTTP 是应用层请求响应协议。",
                steps=["客户端发送请求。", "服务器返回响应。"],
                mistakes="不要把 HTTP 当成传输层协议。",
                similar=["HTTPS", "TCP"],
                final_answer="HTTP 是应用层请求响应协议。",
            ),
            final_answer="HTTP 是应用层请求响应协议。",
            source_usage="model",
        )
        adapter = ProductionQARuntimeAdapter(
            model_name="test-model",
            user_id="u1",
            session_id="s1",
            subject_id="data-structure",
            allow_tools=True,
            allow_search=True,
        )
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=_profile()),
            patch("app.orchestration.graphs.qa.adapter.create_agent", return_value=_FakeAgent(runtime_result)),
        ):
            result = build_graph(adapter=adapter).compile().invoke(
                {
                    "run_id": "run-stable-concept-filtered-rag",
                    "user_id": "u1",
                    "thread_id": "s1",
                    "notebook_id": "data-structure",
                    "user_message": "什么是 HTTP？",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            )

        self.assertEqual(len(result["knowledge_routes"]), 1)
        self.assertEqual(result["knowledge_routes"][0]["subject_id"], "computer-network")
        self.assertEqual(
            result["knowledge_routes"][0]["metadata"]["concept_id"],
            "computer-network.application.http-https",
        )
        self.assertEqual(result["retrieval_report"]["requested_count"], 1)
        self.assertEqual(result["tool_requests"][0]["input"]["concept_id"], "computer-network.application.http-https")

    def test_explicit_named_knowledge_base_routes_to_matching_canonical_subject(self) -> None:
        runtime_result = AgentExecutionResult(
            execution_mode="deterministic_context",
            answer=AnswerSchema(
                topic="HTTP",
                thinking="参考资料后解释 HTTP。",
                steps=["HTTP 是应用层协议。"],
                mistakes="不要混淆 HTTP 与 TCP。",
                similar=["HTTPS", "TCP"],
                final_answer="参考你的资料，HTTP 是应用层协议。",
            ),
            final_answer="参考你的资料，HTTP 是应用层协议。",
            source_usage="model",
        )
        adapter = ProductionQARuntimeAdapter(
            model_name="test-model",
            user_id="u1",
            session_id="s1",
            subject_id="data-structure",
            allow_tools=True,
            allow_search=True,
        )
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=_profile()),
            patch("app.orchestration.graphs.qa.adapter.create_agent", return_value=_FakeAgent(runtime_result)),
        ):
            result = build_graph(adapter=adapter).compile().invoke(
                {
                    "run_id": "run-explicit-named-kb",
                    "user_id": "u1",
                    "thread_id": "s1",
                    "notebook_id": "data-structure",
                    "user_message": "根据计算机网络知识库解释 HTTP",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            )

        routes = result["knowledge_routes"]
        self.assertEqual(routes[0]["subject_id"], "computer-network")
        self.assertEqual(routes[0]["source_reason"], "explicit_named_knowledge_base")
        self.assertNotIn("data-structure", {route["subject_id"] for route in routes})


if __name__ == "__main__":
    unittest.main()
