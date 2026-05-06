from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.practice.quiz_flow import build_quiz_plan_from_state, evaluate_quiz_quality
from app.orchestration.graphs.question_generation.graph import build_graph as build_question_generation_graph
from app.orchestration.graphs.shared.schemas import GraphType, SourcePolicy
from app.shared.schemas.contracts import KnowledgeMasteryRecord, PracticeRecommendation, QuizGenerationContext


def _valid_item(**overrides):
    payload = {
        "question_id": "q-1",
        "question": "HTTP 默认端口是哪个？",
        "options": [
            {"key": "A", "text": "21"},
            {"key": "B", "text": "53"},
            {"key": "C", "text": "80"},
            {"key": "D", "text": "443"},
        ],
        "correct_option": "C",
        "explanation": "HTTP 的默认端口是 80，HTTPS 的默认端口是 443。",
        "option_rationales": {
            "A": "21 通常用于 FTP。",
            "B": "53 通常用于 DNS。",
            "C": "80 是 HTTP 默认端口。",
            "D": "443 是 HTTPS 默认端口。",
        },
        "knowledge_point": "HTTP 默认端口",
        "difficulty": "基础",
        "source_type": "question_bank",
    }
    payload.update(overrides)
    return PracticeRecommendation.model_validate(payload)


class QuizFlowNodesTest(unittest.TestCase):
    def test_mastery_empty_uses_question_and_default_difficulty(self) -> None:
        with patch("app.domains.practice.quiz_flow.get_mastery", return_value=SimpleNamespace(items=[])):
            plan = build_quiz_plan_from_state(
                {
                    "user_id": "u1",
                    "subject_id": "computer-network",
                    "subject_name": "计算机网络",
                    "question": "给我出两道 HTTP 题",
                    "memory": {"error_count": {}},
                }
            )

        self.assertIn("HTTP", plan.focus_points[0])
        self.assertEqual(plan.target_difficulty, "基础")
        self.assertEqual(plan.source, "question")

    def test_mastery_weak_point_has_priority_and_can_raise_difficulty(self) -> None:
        mastery = KnowledgeMasteryRecord(
            user_id="u1",
            subject_id="computer-network",
            knowledge_point="TCP 拥塞控制",
            mastery_score=35,
            mastery_level="weak",
            wrong_count=4,
        )
        with patch("app.domains.practice.quiz_flow.get_mastery", return_value=SimpleNamespace(items=[mastery])):
            plan = build_quiz_plan_from_state(
                {
                    "user_id": "u1",
                    "subject_id": "computer-network",
                    "subject_name": "计算机网络",
                    "question": "随便出题",
                    "memory": {"error_count": {}},
                }
            )

        self.assertEqual(plan.focus_points[0], "TCP 拥塞控制")
        self.assertEqual(plan.target_difficulty, "易错")
        self.assertEqual(plan.source, "mastery")

    def test_quality_check_accepts_complete_relevant_item(self) -> None:
        context = QuizGenerationContext(
            topic="HTTP 默认端口",
            difficulty="基础",
            focus_points=["HTTP"],
            requested_count=1,
        )
        report = evaluate_quiz_quality(items=[_valid_item()], context=context)

        self.assertTrue(report.passed)
        self.assertEqual(report.issues, [])

    def test_quality_check_rejects_missing_rationales_and_difficulty_mismatch(self) -> None:
        context = QuizGenerationContext(
            topic="HTTP 默认端口",
            difficulty="易错",
            focus_points=["HTTP"],
            requested_count=1,
        )
        item = _valid_item(option_rationales={"C": "80 正确。"}, difficulty="基础")
        report = evaluate_quiz_quality(items=[item], context=context)

        self.assertFalse(report.passed)
        self.assertTrue(any("缺少选项解析" in issue for issue in report.issues))
        self.assertTrue(any("难度不匹配" in issue for issue in report.issues))

    def test_question_generation_graph_outputs_quality_checked_items(self) -> None:
        result = build_question_generation_graph().compile().invoke(
            {
                "run_id": "qgen-quiz-flow",
                "user_id": "u1",
                "user_message": "给我出一道 HTTP 题",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertIn("final_response", result)
        self.assertIn("quality_report", result)
        self.assertEqual(result["final_response"]["ui_payload"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)


if __name__ == "__main__":
    unittest.main()
