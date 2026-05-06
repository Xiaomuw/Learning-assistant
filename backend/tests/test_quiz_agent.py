from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.agents.quiz import quiz_agent
from app.domains.practice.generation import build_mixed_practice_items_with_status
from app.shared.schemas.contracts import PracticeRecommendation


class QuizAgentTest(unittest.TestCase):
    def test_quiz_agent_accepts_contract_items_from_practice_domain(self) -> None:
        item = PracticeRecommendation(
            question_id="q-1",
            question="HTTP 默认端口是？",
            options=[
                {"key": "A", "text": "21"},
                {"key": "B", "text": "53"},
                {"key": "C", "text": "80"},
                {"key": "D", "text": "443"},
            ],
            correct_option="C",
            explanation="HTTP 默认端口是 80。",
            option_rationales={"C": "80 是 HTTP 默认端口。"},
            knowledge_point="HTTP 默认端口",
            difficulty="基础",
            source_type="ai_generated",
        )

        with patch(
            "app.orchestration.agents.quiz.build_mixed_practice_items_with_status",
            return_value=SimpleNamespace(
                items=[item],
                status={
                    "requested_count": 2,
                    "generated_count": 1,
                    "question_bank_count": 0,
                    "ai_count": 1,
                    "fallback_count": 0,
                    "partial": True,
                    "degraded_reason": "test partial",
                },
            ),
        ):
            result = quiz_agent(
                {
                    "question": "给我出一道 HTTP 单选题",
                    "subject_id": "general",
                    "subject_name": "通用知识",
                    "memory": {"error_count": {}},
                    "explanation": {},
                }
            )

        self.assertEqual(result["quiz_items"], [item.model_dump()])
        self.assertEqual(result["quiz_generation_status"]["requested_count"], 2)
        self.assertIn("准备了 1 道", result["final_answer"])

    def test_generation_fallback_fills_requested_count_when_ai_generation_fails(self) -> None:
        with (
            patch("app.domains.practice.generation._list_question_bank_items", return_value=[]),
            patch("app.domains.practice.generation._invoke_generation_chain", side_effect=RuntimeError("timeout")),
        ):
            result = build_mixed_practice_items_with_status(
                subject_id="general",
                subject_name="通用知识",
                topic="HTTP 默认端口",
                difficulty="基础",
                count=2,
                original_question="帮我复习 HTTP 默认端口",
                user_style_name="",
                user_style_prompt="",
                short_term_context="",
                session_memory_context="",
                long_term_context="",
                model_name="test-model",
            )

        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.status["requested_count"], 2)
        self.assertEqual(result.status["generated_count"], 2)
        self.assertEqual(result.status["fallback_count"], 2)
        self.assertFalse(result.status["partial"])
        self.assertIn("AI 选择题生成失败", result.status["degraded_reason"])
        self.assertNotEqual(result.items[0].question, result.items[1].question)


if __name__ == "__main__":
    unittest.main()
