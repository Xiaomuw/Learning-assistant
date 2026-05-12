from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.chat.messages import build_message_process
from app.interfaces.api.chat_presenter import event_name_for_node, extract_event_data


class ChatPresenterTest(unittest.TestCase):
    def test_current_langgraph_nodes_keep_existing_sse_events(self) -> None:
        self.assertEqual(event_name_for_node("preflight_node"), "status")
        self.assertEqual(event_name_for_node("learning_context_node"), "status")
        self.assertEqual(event_name_for_node("router"), "routing")
        self.assertEqual(event_name_for_node("guard_node"), "status")
        self.assertEqual(event_name_for_node("rag_node"), "status")
        self.assertEqual(event_name_for_node("web_search_node"), "status")
        self.assertEqual(event_name_for_node("qa_agent_node"), "explanation")
        self.assertEqual(event_name_for_node("qa_answer_guard_node"), "explanation")
        self.assertEqual(event_name_for_node("quiz_mastery_node"), "status")
        self.assertEqual(event_name_for_node("quiz_knowledge_node"), "status")
        self.assertEqual(event_name_for_node("quiz_rag_node"), "status")
        self.assertEqual(event_name_for_node("quiz_context_node"), "status")
        self.assertEqual(event_name_for_node("quiz_generate_node"), "status")
        self.assertEqual(event_name_for_node("quiz_quality_node"), "status")
        self.assertEqual(event_name_for_node("quiz_retry_node"), "status")
        self.assertEqual(event_name_for_node("quiz_output_node"), "quiz")
        self.assertEqual(event_name_for_node("memory_node"), "memory")
        self.assertEqual(event_name_for_node("meta_node"), "explanation")
        self.assertEqual(event_name_for_node("mcq_solver"), "explanation")
        self.assertEqual(event_name_for_node("graph_error_node"), "explanation")
        self.assertEqual(event_name_for_node("finalize_node"), "status")

    def test_removed_nodes_are_not_presenter_special_cases(self) -> None:
        self.assertEqual(event_name_for_node("retriever"), "retriever")
        self.assertEqual(event_name_for_node("explain_node"), "explain_node")
        self.assertEqual(extract_event_data("retriever", {"retrieved_docs": [{"score": 0.9}]}), {})
        self.assertEqual(extract_event_data("explain_node", {"explanation": {"topic": "HTTP"}}), {})

    def test_qa_agent_event_contains_runtime_debug_payload(self) -> None:
        data = extract_event_data(
            "qa_agent_node",
            {
                "question_type": "concept",
                "route": "rag",
                "explanation": {"topic": "HTTP"},
                "final_answer": "HTTP 是应用层协议。",
                "execution_mode": "deterministic_context",
                "tool_calls": [],
                "external_tool_calls": [
                    {
                        "name": "web_search",
                        "capability": "web_search",
                        "provider": "tavily",
                        "success": True,
                        "doc_count": 3,
                    }
                ],
                "web_search_attempted": True,
                "web_search_used": True,
                "web_search_error": "",
                "degraded": False,
                "selected_model_profile": {"model_id": "test-model"},
                "primary_model_id": "primary-test-model",
                "fallback_model_id": "fallback-test-model",
                "fallback_used": True,
                "fallback_reason": "unauthorized_model",
                "model_attempts": [
                    {"model_id": "primary-test-model", "role": "primary", "status": "failed"},
                    {"model_id": "fallback-test-model", "role": "fallback", "status": "ok"},
                ],
                "streaming_mode": "token",
                "streaming_token_count": 18,
                "streaming_degraded_reason": "",
                "model_latency_ms": 1234,
            },
        )

        self.assertEqual(data["explanation"]["topic"], "HTTP")
        self.assertEqual(data["question_type"], "concept")
        self.assertEqual(data["route"], "rag")
        self.assertEqual(data["execution_mode"], "deterministic_context")
        self.assertEqual(data["selected_model_profile"]["model_id"], "test-model")
        self.assertTrue(data["fallback_used"])
        self.assertEqual(data["primary_model_id"], "primary-test-model")
        self.assertEqual(data["fallback_model_id"], "fallback-test-model")
        self.assertEqual(len(data["model_attempts"]), 2)
        self.assertEqual(data["streaming_mode"], "token")
        self.assertEqual(data["streaming_token_count"], 18)
        self.assertEqual(data["streaming_degraded_reason"], "")
        self.assertEqual(data["model_latency_ms"], 1234)
        self.assertTrue(data["web_search_attempted"])
        self.assertTrue(data["web_search_used"])
        self.assertEqual(data["external_tool_calls"][0]["name"], "web_search")
        self.assertEqual(data["external_tool_calls"][0]["source"], "web")
        self.assertNotIn("provider", data["external_tool_calls"][0])
        self.assertNotIn("tavily", json.dumps(data, ensure_ascii=False).lower())

    def test_message_process_keeps_model_call_evidence_for_history(self) -> None:
        process = build_message_process(
            {
                "question_type": "meta",
                "route": "fast",
                "final_answer": "当前这次请求使用的模型标识是 deepseek-v4-pro。",
                "execution_mode": "direct_answer",
                "selected_model_profile": {
                    "model_id": "deepseek-v4-pro",
                    "family": "DeepSeek",
                    "provider": "DeepSeek",
                },
                "primary_model_id": "deepseek-v4-pro",
                "model_attempts": [
                    {"model_id": "deepseek-v4-pro", "role": "primary", "status": "ok"},
                ],
                "streaming_mode": "token",
                "streaming_token_count": 12,
                "streaming_degraded_reason": "provider_stream_returned_no_chunks",
                "model_latency_ms": 860,
            }
        )

        self.assertIsNotNone(process)
        execution = process["execution"]
        self.assertEqual(execution["modelId"], "deepseek-v4-pro")
        self.assertEqual(execution["callStatus"], "ok")
        self.assertEqual(execution["streamingMode"], "token")
        self.assertEqual(execution["streamingTokenCount"], 12)
        self.assertEqual(execution["streamingDegradedReason"], "provider_stream_returned_no_chunks")
        self.assertEqual(execution["modelLatencyMs"], 860)
        self.assertEqual(execution["modelAttempts"][0]["status"], "ok")
        self.assertTrue(any("流式 12 段" in stage["detail"] for stage in process["stages"]))

    def test_rag_event_contains_retrieval_debug_payload(self) -> None:
        data = extract_event_data(
            "rag_node",
            {
                "retrieved_docs": [{"score": 0.91}, {"score": 0.74}],
                "contextual_query": "HTTP 默认端口",
                "retrieval_diagnosis": {"diagnosis": "ready"},
                "rag_ready": True,
                "web_search_required": False,
            },
        )

        self.assertEqual(data["doc_count"], 2)
        self.assertEqual(data["top_scores"], [0.91, 0.74])
        self.assertTrue(data["rag_ready"])
        self.assertFalse(data["web_search_required"])

    def test_router_event_contains_route_and_learning_context(self) -> None:
        data = extract_event_data(
            "router",
            {
                "question_type": "concept",
                "route": "rag",
                "route_confidence": 0.92,
                "route_reason": "依据当前资料回答。",
                "learning_context": {
                    "mode": "teach",
                    "level": "intermediate",
                    "need_steps": True,
                    "need_examples": False,
                },
            },
        )

        self.assertEqual(data["route"], "rag")
        self.assertEqual(data["route_confidence"], 0.92)
        self.assertTrue(data["learning_context"]["need_steps"])

    def test_guard_event_contains_tool_permissions(self) -> None:
        data = extract_event_data(
            "guard_node",
            {
                "route": "agent",
                "guard": {"allow_tools": True, "allow_search": True, "reason": "需要最新信息"},
                "allow_tools": True,
                "allow_search": True,
            },
        )

        self.assertEqual(data["route"], "agent")
        self.assertTrue(data["allow_tools"])
        self.assertTrue(data["guard"]["allow_search"])

    def test_web_search_event_contains_capability_debug_payload(self) -> None:
        data = extract_event_data(
            "web_search_node",
            {
                "retrieved_docs": [{"score": 0.91}, {"score": 0.74}],
                "retrieval_diagnosis": {"diagnosis": "ready"},
                "external_tool_calls": [
                    {
                        "name": "web_search",
                        "capability": "web_search",
                        "provider": "tavily",
                        "success": True,
                        "doc_count": 2,
                    }
                ],
                "web_search_attempted": True,
                "web_search_used": True,
            },
        )

        self.assertEqual(data["doc_count"], 2)
        self.assertEqual(data["top_scores"], [0.91, 0.74])
        self.assertTrue(data["web_search_used"])
        self.assertEqual(data["external_tool_calls"][0]["name"], "web_search")
        self.assertEqual(data["external_tool_calls"][0]["source"], "web")
        self.assertNotIn("tavily", json.dumps(data, ensure_ascii=False).lower())

    def test_unknown_tool_provider_is_not_exposed_as_source(self) -> None:
        data = extract_event_data(
            "qa_agent_node",
            {
                "external_tool_calls": [
                    {
                        "name": "custom_tool",
                        "capability": "custom",
                        "provider": "raw-provider-name",
                        "success": True,
                    }
                ]
            },
        )

        self.assertEqual(data["external_tool_calls"][0]["source"], "tool")
        self.assertNotIn("provider", data["external_tool_calls"][0])
        self.assertNotIn("raw-provider-name", json.dumps(data, ensure_ascii=False))

    def test_message_process_displays_web_search_tool_call(self) -> None:
        process = build_message_process(
            {
                "question_type": "concept",
                "route": "agent",
                "explanation": {"thinking": "当前 notebook 未命中，已使用网络资料解释。"},
                "retrieved_docs": [{"score": 0.92}, {"score": 0.7}],
                "retrieval_diagnosis": {"diagnosis": "ready"},
                "web_search_used": True,
                "tool_calls": [],
                "external_tool_calls": [
                    {
                        "name": "web_search",
                        "capability": "web_search",
                        "provider": "tavily",
                        "success": True,
                        "doc_count": 2,
                    }
                ],
            }
        )

        self.assertIsNotNone(process)
        self.assertEqual(process["toolCalls"][0]["label"], "网络搜索")
        self.assertEqual(process["toolCalls"][0]["docCount"], 2)
        self.assertNotIn("tavily", json.dumps(process, ensure_ascii=False).lower())
        self.assertTrue(any(stage["key"] == "routing" and "工具增强" in stage["detail"] for stage in process["stages"]))

    def test_finalize_event_exposes_observability_without_changing_done_contract(self) -> None:
        data = extract_event_data(
            "finalize_node",
            {
                "finalized": True,
                "final_response_type": "explanation",
                "route_decision": "preflight_node->router->rag_node->qa_agent_node->memory_node->finalize_node",
                "graph_warnings": ["memory warning"],
                "degraded": False,
            },
        )

        self.assertTrue(data["finalized"])
        self.assertEqual(data["final_response_type"], "explanation")
        self.assertIn("qa_agent_node", data["route_decision"])

    def test_final_event_exposes_streaming_degraded_reason(self) -> None:
        data = extract_event_data(
            "final",
            {
                "finalized": True,
                "question_type": "concept",
                "route": "explain",
                "final_answer": "HTTP 是应用层协议。",
                "degraded": False,
                "streaming_mode": "node",
                "streaming_token_count": 0,
                "streaming_degraded_reason": "provider_stream_returned_no_chunks",
                "model_latency_ms": 1200,
            },
        )

        self.assertEqual(data["streaming_mode"], "node")
        self.assertEqual(data["streaming_token_count"], 0)
        self.assertEqual(data["streaming_degraded_reason"], "provider_stream_returned_no_chunks")
        self.assertEqual(data["model_latency_ms"], 1200)

    def test_answer_events_can_include_accumulated_question_type(self) -> None:
        data = extract_event_data(
            "teaching_response_node",
            {
                "question_type": "application",
                "teaching_input_type": "application",
                "explanation": {"topic": "递归", "thinking": "先判断适用场景。"},
                "final_answer": "先看问题能否拆成同类子问题。",
            },
        )

        self.assertEqual(data["question_type"], "application")
        self.assertEqual(data["teaching_input_type"], "application")
        self.assertEqual(data["explanation"]["topic"], "递归")


if __name__ == "__main__":
    unittest.main()
