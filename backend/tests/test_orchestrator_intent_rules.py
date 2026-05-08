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

    def test_mastery_rule_routes_mastery_requests(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "评估我的掌握度"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.MASTERY.value)

    def test_help_rule_routes_incomplete_requests_to_fallback(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "help"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)

    def test_default_rule_routes_learning_questions_to_qa(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "什么是 HTTP？"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)

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
