from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.practice.service import run_due_practice_attempt_finalization_jobs
from app.domains.practice.attempts import PracticeAttemptFinalization, finalize_practice_attempt_analysis
from app.infrastructure.db.database import Base
from app.infrastructure.db.models import (
    PracticeAttemptFinalizationJobModel,
    PracticeAttemptModel,
    UserMemoryModel,
)
import app.infrastructure.db.repositories.practice as practice_repo
import app.infrastructure.db.repositories.users as users_repo
from app.infrastructure.db.repositories._shared import utcnow
from app.infrastructure.db.repositories.users import MAX_FINALIZED_PRACTICE_ATTEMPT_IDS
from app.shared.schemas.contracts import MasteryEvaluationResult, PracticeRecommendation


def _quiz_item(question_id: str = "q1") -> PracticeRecommendation:
    return PracticeRecommendation(
        question_id=question_id,
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
        knowledge_point="HTTP",
    )


class PracticeFinalizerJobRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.tables = [
            UserMemoryModel.__table__,
            PracticeAttemptModel.__table__,
            PracticeAttemptFinalizationJobModel.__table__,
        ]
        Base.metadata.create_all(bind=self.engine, tables=self.tables)
        self.patches = [
            patch("app.infrastructure.db.repositories.practice.session_scope", self.session_scope),
            patch("app.infrastructure.db.repositories.users.session_scope", self.session_scope),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        Base.metadata.drop_all(bind=self.engine, tables=self.tables)
        self.engine.dispose()

    @contextmanager
    def session_scope(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def test_create_claim_complete_fail_and_list_due_state_machine(self) -> None:
        attempt, job = practice_repo.create_practice_attempt_record_with_finalization_job(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            question_id="q1",
            question_snapshot=_quiz_item().model_dump(),
            selected_option="A",
            is_correct=False,
            knowledge_point="HTTP",
            idempotency_key="attempt-key-1",
        )
        duplicate_attempt, duplicate_job = practice_repo.create_practice_attempt_record_with_finalization_job(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            question_id="q1",
            question_snapshot=_quiz_item().model_dump(),
            selected_option="A",
            is_correct=False,
            knowledge_point="HTTP",
            idempotency_key="attempt-key-1",
        )
        self.assertEqual(duplicate_attempt.id, attempt.id)
        self.assertEqual(duplicate_job["job_id"], job["job_id"])
        self.assertEqual([item["job_id"] for item in practice_repo.list_due_practice_attempt_finalization_jobs()], [job["job_id"]])

        claimed = practice_repo.claim_practice_attempt_finalization_job(job["job_id"])
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempt_count"], 1)
        self.assertIsNone(practice_repo.claim_practice_attempt_finalization_job(job["job_id"]))
        self.assertEqual(practice_repo.list_due_practice_attempt_finalization_jobs(), [])

        practice_repo.complete_practice_attempt_finalization_job(job["job_id"])
        completed = practice_repo.get_practice_attempt_finalization_job(job["job_id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["locked_at"], "")
        self.assertIsNone(practice_repo.claim_practice_attempt_finalization_job(job["job_id"]))

        _, retry_job = practice_repo.create_practice_attempt_record_with_finalization_job(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            question_id="q2",
            question_snapshot=_quiz_item("q2").model_dump(),
            selected_option="A",
            is_correct=False,
            knowledge_point="HTTP",
            idempotency_key="attempt-key-2",
        )
        practice_repo.claim_practice_attempt_finalization_job(retry_job["job_id"])
        self.assertEqual(practice_repo.fail_practice_attempt_finalization_job(retry_job["job_id"], "boom"), "failed")
        failed = practice_repo.get_practice_attempt_finalization_job(retry_job["job_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["locked_at"], "")
        self.assertNotEqual(failed["next_run_at"], "")
        self.assertEqual(practice_repo.list_due_practice_attempt_finalization_jobs(), [])
        self.assertIsNone(practice_repo.claim_practice_attempt_finalization_job(retry_job["job_id"]))

        with self.session_scope() as session:
            row = session.get(PracticeAttemptFinalizationJobModel, retry_job["job_id"])
            row.next_run_at = utcnow() - timedelta(minutes=1)
        self.assertEqual(practice_repo.claim_practice_attempt_finalization_job(retry_job["job_id"])["attempt_count"], 2)

        with self.session_scope() as session:
            row = session.get(PracticeAttemptFinalizationJobModel, retry_job["job_id"])
            row.status = "running"
            row.locked_at = utcnow() - practice_repo.FINALIZATION_JOB_STALE_TIMEOUT - timedelta(seconds=1)
        due = practice_repo.list_due_practice_attempt_finalization_jobs()
        self.assertEqual([item["job_id"] for item in due], [retry_job["job_id"]])
        self.assertEqual(practice_repo.claim_practice_attempt_finalization_job(retry_job["job_id"])["attempt_count"], 3)

        with self.session_scope() as session:
            row = session.get(PracticeAttemptFinalizationJobModel, retry_job["job_id"])
            row.attempt_count = practice_repo.FINALIZATION_JOB_MAX_ATTEMPTS
        self.assertEqual(practice_repo.fail_practice_attempt_finalization_job(retry_job["job_id"], "too_many"), "dead")
        dead = practice_repo.get_practice_attempt_finalization_job(retry_job["job_id"])
        self.assertEqual(dead["status"], "dead")
        self.assertEqual(practice_repo.list_due_practice_attempt_finalization_jobs(), [])
        self.assertIsNone(practice_repo.claim_practice_attempt_finalization_job(retry_job["job_id"]))

    def test_legacy_memory_finalization_is_idempotent_by_attempt_id(self) -> None:
        quiz_item = _quiz_item()
        finalization = PracticeAttemptFinalization(
            user_id="u-memory",
            session_id="",
            subject_id="network",
            quiz_item=quiz_item,
            selected_option="A",
            legacy_attempt={"id": "legacy-attempt-1"},
        )
        evaluation = MasteryEvaluationResult(
            subject_id="network",
            knowledge_point="HTTP",
            is_correct=False,
            feedback="继续复盘 HTTP。",
        )
        with patch("app.domains.practice.attempts.evaluate_practice_answer", return_value=evaluation):
            first = finalize_practice_attempt_analysis(finalization)
            second = finalize_practice_attempt_analysis(finalization)

        self.assertEqual(first.analysis_status, "completed")
        self.assertEqual(second.analysis_status, "completed")
        memory = users_repo.get_user_memory_record("u-memory")
        self.assertEqual(memory.error_count, {"HTTP": 1})
        self.assertEqual(memory.weak_points, ["HTTP"])
        self.assertEqual(memory.recent_topics, ["HTTP"])
        self.assertFalse(hasattr(memory, "finalized_practice_attempt_ids"))
        with self.session_scope() as session:
            row = session.get(UserMemoryModel, "u-memory")
            self.assertEqual(row.finalized_practice_attempt_ids, ["legacy-attempt-1"])

    def test_finalized_practice_attempt_ids_are_capped(self) -> None:
        with self.session_scope() as session:
            row = UserMemoryModel(user_id="u-cap")
            row.finalized_practice_attempt_ids = [
                f"old-{index}" for index in range(MAX_FINALIZED_PRACTICE_ATTEMPT_IDS + 5)
            ]
            session.add(row)

        _, updated = users_repo.apply_practice_attempt_memory_finalization(
            "u-cap",
            legacy_attempt_id="new-attempt",
            weak_points=[],
            error_count={},
            recent_topics=[],
            last_session="",
        )

        self.assertTrue(updated)
        with self.session_scope() as session:
            row = session.get(UserMemoryModel, "u-cap")
            self.assertEqual(len(row.finalized_practice_attempt_ids), MAX_FINALIZED_PRACTICE_ATTEMPT_IDS)
            self.assertEqual(row.finalized_practice_attempt_ids[0], "new-attempt")
            self.assertNotIn(f"old-{MAX_FINALIZED_PRACTICE_ATTEMPT_IDS + 4}", row.finalized_practice_attempt_ids)


class PracticeFinalizerRunnerTest(unittest.TestCase):
    def test_due_runner_invokes_each_due_job(self) -> None:
        with (
            patch(
                "app.application.practice.service.list_due_practice_attempt_finalization_jobs",
                return_value=[{"job_id": "job-1"}, {"id": "job-2"}],
            ) as list_due,
            patch("app.application.practice.service.finalize_attempt_analysis_job") as finalize_job,
        ):
            finalize_job.side_effect = ["completed", "failed"]
            summary = run_due_practice_attempt_finalization_jobs(limit=2)

        self.assertEqual(
            summary,
            {"due": 2, "claimed": 2, "completed": 1, "failed": 1, "dead": 0, "skipped": 0},
        )
        list_due.assert_called_once_with(limit=2)
        finalize_job.assert_any_call("job-1")
        finalize_job.assert_any_call("job-2")


if __name__ == "__main__":
    unittest.main()
