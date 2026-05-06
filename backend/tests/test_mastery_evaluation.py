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

from app.domains.mastery.evaluation import evaluate_practice_answer, normalize_answer
from app.services.rag.rag_service import RagContextResult
from app.shared.schemas.contracts import (
    KnowledgeMasteryRecord,
    PracticeRecommendation,
    RetrievalDiagnostics,
    RetrievedDocument,
)


def _quiz() -> PracticeRecommendation:
    return PracticeRecommendation(
        question_id="q-http-port",
        question="HTTP 默认端口是多少？",
        options=[
            {"key": "A", "text": "20"},
            {"key": "B", "text": "53"},
            {"key": "C", "text": "80"},
            {"key": "D", "text": "443"},
        ],
        correct_option="C",
        explanation="HTTP 默认端口是 80。",
        option_rationales={
            "A": "20 常见于 FTP 数据连接，不是 HTTP。",
            "B": "53 是 DNS 默认端口。",
            "C": "HTTP 明文服务默认使用 80 端口。",
            "D": "443 是 HTTPS 默认端口。",
        },
        knowledge_point="HTTP 默认端口",
        difficulty="基础",
    )


def _ready_rag() -> RagContextResult:
    return RagContextResult(
        docs=[
            RetrievedDocument(
                doc_id="doc-1",
                content="HTTP 明文服务默认端口为 80，HTTPS 默认端口为 443。",
                metadata={"knowledge_point": "HTTP 默认端口"},
                score=0.92,
                distance=0.08,
            )
        ],
        diagnosis=RetrievalDiagnostics(
            query="HTTP 默认端口",
            hit_count=1,
            top_score=0.92,
            diagnosis="ready",
            coverage_level="ready",
        ),
        contextual_query="HTTP 默认端口",
        rag_ready=True,
    )


class MasteryEvaluationTest(unittest.TestCase):
    def test_normalize_mcq_answer(self) -> None:
        result = normalize_answer(selected_option=" c ", quiz_item=_quiz())

        self.assertEqual(result.answer_type, "mcq")
        self.assertEqual(result.normalized_answer, "C")
        self.assertTrue(result.is_valid)

    def test_correct_answer_gets_positive_feedback(self) -> None:
        with (
            patch("app.domains.mastery.evaluation.retrieve_context", return_value=_ready_rag()),
            patch(
                "app.domains.mastery.evaluation.record_attempt",
                return_value=KnowledgeMasteryRecord(
                    user_id="u1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    attempt_count=1,
                    correct_count=1,
                    mastery_score=86,
                    mastery_level="mastered",
                ),
            ),
        ):
            result = evaluate_practice_answer(
                user_id="u1",
                subject_id="network",
                quiz_item=_quiz(),
                selected_option="C",
            )

        self.assertTrue(result.is_correct)
        self.assertEqual(result.mastery_level, "mastered")
        self.assertEqual(result.score_breakdown.accuracy, 100)
        self.assertIn("判断是对的", result.feedback)

    def test_wrong_answer_marks_weak_point(self) -> None:
        with (
            patch("app.domains.mastery.evaluation.retrieve_context", return_value=_ready_rag()),
            patch(
                "app.domains.mastery.evaluation.record_attempt",
                return_value=KnowledgeMasteryRecord(
                    user_id="u1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    attempt_count=1,
                    wrong_count=1,
                    mastery_score=25,
                    mastery_level="weak",
                ),
            ),
        ):
            result = evaluate_practice_answer(
                user_id="u1",
                subject_id="network",
                quiz_item=_quiz(),
                selected_option="D",
            )

        self.assertFalse(result.is_correct)
        self.assertIn("HTTP 默认端口", result.weak_points)
        self.assertIn("443 是 HTTPS 默认端口", result.feedback)

    def test_low_confidence_retrieval_retries_once(self) -> None:
        low = RagContextResult(
            docs=[],
            diagnosis=RetrievalDiagnostics(
                query="HTTP 默认端口",
                hit_count=0,
                top_score=0,
                diagnosis="no_matching_docs",
            ),
            contextual_query="HTTP 默认端口",
            rag_ready=False,
        )
        with (
            patch("app.domains.mastery.evaluation.retrieve_context", side_effect=[low, _ready_rag()]) as retrieve_mock,
            patch(
                "app.domains.mastery.evaluation.record_attempt",
                return_value=KnowledgeMasteryRecord(
                    user_id="u1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    attempt_count=1,
                    correct_count=1,
                    mastery_score=70,
                    mastery_level="learning",
                ),
            ),
        ):
            result = evaluate_practice_answer(
                user_id="u1",
                subject_id="network",
                quiz_item=_quiz(),
                selected_option="C",
            )

        self.assertEqual(retrieve_mock.call_count, 2)
        self.assertEqual(result.reference_doc_count, 1)
        self.assertEqual(result.retrieval_diagnosis, "ready")

    def test_rag_failure_does_not_block_mastery_update(self) -> None:
        with (
            patch("app.domains.mastery.evaluation.retrieve_context", side_effect=RuntimeError("rag unavailable")),
            patch(
                "app.domains.mastery.evaluation.record_attempt",
                return_value=KnowledgeMasteryRecord(
                    user_id="u1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    attempt_count=1,
                    correct_count=1,
                    mastery_score=68,
                    mastery_level="learning",
                ),
            ),
        ):
            result = evaluate_practice_answer(
                user_id="u1",
                subject_id="network",
                quiz_item=_quiz(),
                selected_option="C",
            )

        self.assertTrue(result.is_correct)
        self.assertEqual(result.reference_doc_count, 0)
        self.assertIn("reference_confidence_low", result.score_breakdown.issues)


if __name__ == "__main__":
    unittest.main()
