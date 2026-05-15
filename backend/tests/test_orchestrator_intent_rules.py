from __future__ import annotations

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

from app.orchestration.graphs.orchestrator.intent_rules import resolve_intent_decision
from app.orchestration.graphs.orchestrator.route_decider import BoundaryRoute
from app.orchestration.graphs.orchestrator.schemas import OrchestratorIntent
from app.shared.schemas.agent_graphs import GraphType


class OrchestratorIntentRulesTest(unittest.TestCase):
    def test_request_errors_route_to_fallback(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "",
                "errors": [{"code": "empty_user_message", "message": "用户消息不能为空。"}],
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)

    def test_request_error_has_priority_over_quiz_keywords(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "errors": [{"code": "empty_user_message", "message": "用户消息不能为空。"}],
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertNotIn("quiz_request", result)

    def test_quiz_generate_rule_uses_resolved_quiz_request(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "帮我出题练习 HTTP"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(result["quiz_request"]["action"], "generate_practice_pack")
        self.assertEqual(result["quiz_request"]["topic"], "HTTP")

    def test_context_dependent_quiz_without_context_returns_clarification(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "根据我的笔记帮我出几道 HTTP 题"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)
        self.assertEqual(result["route_decision"]["route"], "practice_generation")
        self.assertTrue(result["quiz_clarification"]["recommended_options"])

    def test_weak_point_quiz_request_prefers_question_generation_over_mastery(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "根据我的薄弱点出题",
                "chat_runtime_context": {"weak_points": ["TCP 慢启动"]},
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(result["quiz_request"]["topic"], "TCP 慢启动")

    def test_quiz_clarify_rule_returns_clarification_payload(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "帮我出点题"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["quiz_request"]["action"], "clarify_quiz_request")
        self.assertTrue(result["quiz_clarification"]["recommended_options"])

    def test_unsupported_quiz_type_routes_to_clarification(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "围绕 HTTP 出 3 道多选题"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["quiz_request"]["action"], "clarify_quiz_request")
        self.assertEqual(result["quiz_request"]["clarification_reason"], "unsupported_question_type")

    def test_chinese_intent_regression_terms_route_correctly(self) -> None:
        quiz = resolve_intent_decision({"user_id": "u1", "user_message": "来一组 HTTP"})
        correction = resolve_intent_decision({"user_id": "u1", "user_message": "帮我批改这道题，哪里不对"})
        weakness = resolve_intent_decision({"user_id": "u1", "user_message": "我的短板和弱项是什么"})

        self.assertEqual(quiz["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(correction["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(weakness["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)

    def test_mastery_rule_routes_mastery_requests(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "评估我的掌握度"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.MASTERY.value)

    def test_answer_check_question_routes_to_qa_not_mastery(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "评估一下这个答案对不对"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)

    def test_help_rule_routes_incomplete_requests_to_fallback(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "help"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)

    def test_single_question_mark_routes_to_fallback(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "?"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)

    def test_default_rule_routes_learning_questions_to_qa(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "什么是 HTTP？"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)

    def test_question_construction_explanation_routes_to_qa_not_question_generation(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "帮我讲讲怎么出这道题"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)

    def test_arithmetic_drill_request_uses_latest_user_topic_not_stale_context(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "帮我出几道一百以内的加减法运算",
                "chat_runtime_context": {
                    "session_memory": {"active_topic": "1+1=2"},
                    "current_question_topic": "1+1=2",
                },
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(result["quiz_request"]["action"], "generate_practice_pack")
        self.assertIn("加减法运算", result["quiz_request"]["topic"])
        self.assertNotEqual(result["quiz_request"]["topic"], "1+1=2")

    def test_regular_question_with_question_mark_still_routes_to_qa(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "TCP 为什么要三次握手？"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)

    def test_simple_fact_routes_to_direct_response(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "1+1等于几"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.DIRECT_RESPONSE.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)
        self.assertEqual(result["route_decision"]["route"], BoundaryRoute.SIMPLE_FACT.value)
        self.assertEqual(result["trace_records"][0]["stage"], "route_decider")
        self.assertEqual(result["trace_records"][0]["route"], BoundaryRoute.SIMPLE_FACT.value)

    def test_meta_tool_usage_routes_to_direct_response(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "刚刚有联网搜索吗",
                "messages": [
                    {
                        "role": "assistant",
                        "toolInvocationTrace": {
                            "toolCallCount": 0,
                            "toolCalls": [],
                            "didUseWebSearch": False,
                            "didUseAnyTool": False,
                        },
                    }
                ],
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.DIRECT_RESPONSE.value)
        self.assertEqual(result["route_decision"]["route"], BoundaryRoute.META_TOOL_USAGE.value)

    def test_realtime_without_web_routes_to_direct_response(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "今年 GPT 发布到哪个版本了",
                "source_policy": "notebook_only",
                "runtime_context": {"available_capabilities": ["web_search"]},
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.DIRECT_RESPONSE.value)
        self.assertEqual(result["route_decision"]["route"], BoundaryRoute.REALTIME_OR_FRESH.value)
        self.assertFalse(result["route_decision"]["policy"]["allow_web"])

    def test_realtime_with_web_enters_qagraph(self) -> None:
        result = resolve_intent_decision(
            {
                "user_id": "u1",
                "user_message": "今年 GPT 发布到哪个版本了",
                "source_policy": "open_tools",
                "runtime_context": {"available_capabilities": ["web_search"]},
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["route_decision"]["route"], BoundaryRoute.REALTIME_OR_FRESH.value)
        self.assertTrue(result["route_decision"]["policy"]["allow_web"])

    def test_custom_intent_rule_can_short_circuit_default_rules(self) -> None:
        class CustomRule:
            def decide(self, context):
                return {
                    "intent_decision": {
                        "intent": OrchestratorIntent.EVALUATE_MASTERY.value,
                        "confidence": 1.0,
                        "reason": "custom rule",
                        "target_graph_type": GraphType.MASTERY.value,
                    }
                }

        result = resolve_intent_decision(
            {"user_id": "u1", "user_message": "什么是 HTTP？"},
            rules=(CustomRule(),),
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)
        self.assertEqual(result["intent_decision"]["reason"], "custom rule")


if __name__ == "__main__":
    unittest.main()
