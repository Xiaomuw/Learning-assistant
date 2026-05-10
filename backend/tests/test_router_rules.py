from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.graphs.orchestrator.intent_rules import resolve_intent_decision
from app.orchestration.graphs.orchestrator.schemas import OrchestratorIntent
from app.shared.schemas.agent_graphs import GraphType


class RouterRulesTest(unittest.TestCase):
    def test_practice_questions_route_to_question_generation_graph(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "给我出两道数据库索引题"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)

    def test_weak_point_review_routes_to_mastery_graph(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "帮我看看薄弱点"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.MASTERY.value)

    def test_incomplete_help_routes_to_orchestrator_fallback(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "help"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.ORCHESTRATOR.value)

    def test_normal_learning_question_routes_to_qa_graph(self) -> None:
        result = resolve_intent_decision({"user_id": "u1", "user_message": "什么是 HTTP？"})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)


if __name__ == "__main__":
    unittest.main()
