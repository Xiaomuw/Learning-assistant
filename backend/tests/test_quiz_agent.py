from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.practice.generation import build_mixed_practice_items_with_status


class QuizGenerationDomainTest(unittest.TestCase):
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

    def test_question_bank_failure_does_not_block_deterministic_fallback(self) -> None:
        with (
            patch("app.domains.practice.generation._list_question_bank_items", side_effect=RuntimeError("db down")),
            patch("app.domains.practice.generation._invoke_generation_chain", side_effect=RuntimeError("model down")),
        ):
            result = build_mixed_practice_items_with_status(
                subject_id="data-structure",
                subject_name="数据结构与算法",
                topic="数据结构与算法",
                difficulty="基础",
                count=5,
                original_question="出一些数据结构的题目",
                user_style_name="",
                user_style_prompt="",
                short_term_context="",
                session_memory_context="",
                long_term_context="",
                model_name="test-model",
            )

        questions = "\n".join(item.question for item in result.items)
        self.assertEqual(len(result.items), 5)
        self.assertEqual(result.status["generated_count"], 5)
        self.assertEqual(result.status["fallback_count"], 5)
        self.assertTrue(result.status["question_bank_unavailable"])
        self.assertEqual(result.status["question_bank_error_type"], "RuntimeError")
        self.assertTrue(result.status["ai_generation_failed"])
        self.assertFalse(result.status["partial"])
        self.assertIn("题库读取失败", result.status["degraded_reason"])
        self.assertIn("AI 选择题生成失败", result.status["degraded_reason"])
        self.assertIn("数组", questions)
        self.assertNotIn("HTTP", questions)


if __name__ == "__main__":
    unittest.main()
