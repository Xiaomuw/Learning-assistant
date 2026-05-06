from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.chat.orchestrator_runtime import _quiz_items_from_child_payload
from app.domains.practice.attempts import record_practice_attempt_and_update_memory
from app.domains.practice.common import normalize_practice_source_type, normalize_quiz_item
from app.shared.schemas.contracts import MasteryEvaluationResult, PracticeRecommendation


class PracticeSourceNormalizationTest(unittest.TestCase):
    def test_internal_generation_source_maps_to_ai_generated_for_chat_quiz_items(self) -> None:
        items = _quiz_items_from_child_payload(
            {
                "question_items": [
                    {
                        "id": "q1",
                        "stem": "HTTP 默认端口是？",
                        "options": [
                            {"key": "A", "text": "20"},
                            {"key": "B", "text": "53"},
                            {"key": "C", "text": "80"},
                            {"key": "D", "text": "443"},
                        ],
                        "primary_concept_id": "HTTP",
                        "difficulty": "基础",
                        "generation_source": "deterministic_adapter",
                        "answer_key": {
                            "correct_option": "C",
                            "explanation": "HTTP 默认端口是 80。",
                            "option_rationales": {"C": "80 是 HTTP 默认端口。"},
                        },
                    }
                ]
            }
        )

        self.assertEqual(items[0]["source_type"], "ai_generated")
        self.assertEqual(items[0]["source_name"], "QuestionGenerationGraph")

    def test_normalize_quiz_item_keeps_source_type_compatible_with_attempt_table(self) -> None:
        item = normalize_quiz_item(
            {
                "question_id": "q1",
                "question": "HTTP 默认端口是？",
                "options": [
                    {"key": "A", "text": "20"},
                    {"key": "B", "text": "53"},
                    {"key": "C", "text": "80"},
                    {"key": "D", "text": "443"},
                ],
                "correct_option": "C",
                "explanation": "HTTP 默认端口是 80。",
                "option_rationales": {"C": "80 是 HTTP 默认端口。"},
                "knowledge_point": "HTTP",
                "source_type": "deterministic_adapter",
            }
        )

        self.assertEqual(item.source_type, "ai_generated")
        self.assertEqual(normalize_practice_source_type("question_bank"), "question_bank")

    def test_submit_attempt_normalizes_internal_source_before_persisting(self) -> None:
        captured: dict[str, str] = {}

        def fake_create_attempt(**kwargs):
            captured.update(kwargs)
            return kwargs

        with (
            patch(
                "app.domains.practice.attempts.evaluate_practice_answer",
                return_value=MasteryEvaluationResult(
                    subject_id="general",
                    knowledge_point="HTTP",
                    normalized_answer="C",
                    is_correct=True,
                    score=100,
                    mastery_score=100,
                    mastery_level="mastered",
                    feedback="回答正确。",
                ),
            ),
            patch("app.domains.practice.attempts._create_practice_attempt", side_effect=fake_create_attempt),
            patch(
                "app.domains.practice.attempts._get_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": []},
            ),
            patch(
                "app.domains.practice.attempts._save_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": ["HTTP"], "last_session": ""},
            ),
        ):
            record_practice_attempt_and_update_memory(
                user_id="u1",
                session_id="",
                subject_id="general",
                quiz_item=PracticeRecommendation(
                    question_id="q1",
                    question="HTTP 默认端口是？",
                    options=[
                        {"key": "A", "text": "20"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    correct_option="C",
                    explanation="HTTP 默认端口是 80。",
                    option_rationales={"C": "80 是 HTTP 默认端口。"},
                    knowledge_point="HTTP",
                    source_type="deterministic_adapter",
                ),
                selected_option="C",
            )

        self.assertEqual(captured["source_type"], "ai_generated")


if __name__ == "__main__":
    unittest.main()
