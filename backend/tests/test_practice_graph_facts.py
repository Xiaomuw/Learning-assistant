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

from app.application.practice.graph_facts import maybe_dual_write_practice_attempt, update_graph_mastery_from_practice_attempt
from app.application.practice.service import finalize_attempt_analysis, finalize_attempt_analysis_job, submit_attempt
from app.domains.practice.attempts import PracticeAttemptFinalization
from app.shared.schemas.contracts import PracticeRecommendation, PracticeSubmissionResult, UserMemoryRecord


def _quiz_item() -> PracticeRecommendation:
    return PracticeRecommendation(
        question_id="q1",
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


def _submission_result() -> PracticeSubmissionResult:
    return PracticeSubmissionResult(
        is_correct=True,
        correct_option="C",
        explanation="HTTP 默认端口是 80。",
        option_rationales={"C": "80 是 HTTP 默认端口。"},
        memory=UserMemoryRecord(),
    )


class _FakeGraphRuns:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def start_run(self, payload):
        self.started.append(payload)
        return payload["run_id"]

    def finish_run(self, graph_run_id, payload):
        self.finished.append((graph_run_id, payload))

    def record_audit_event(self, payload):
        return None


class _FakeEvents:
    def __init__(self) -> None:
        self.events = []

    def append(self, event):
        self.events.append(event)
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100):
        return []


class _FakeAttempts:
    def __init__(self) -> None:
        self.attempts = []

    def create_attempt(self, payload):
        self.attempts.append(payload)
        return payload["attempt_id"]

    def list_recent_attempts(self, *, user_id: str, limit: int = 100):
        return []


class _FakeRepos:
    def __init__(self) -> None:
        self.graph_runs = _FakeGraphRuns()
        self.learning_events = _FakeEvents()
        self.attempts = _FakeAttempts()


class _FakeCompiledGraph:
    def invoke(self, state):
        return {"mastery_snapshot_ids": ["snapshot-1"], "state": state}


class _FakeGraph:
    def compile(self):
        return _FakeCompiledGraph()


class PracticeGraphFactsTest(unittest.TestCase):
    def test_submit_attempt_sync_path_returns_domain_result_without_dual_write(self) -> None:
        expected = _submission_result()
        with (
            patch("app.application.practice.service.record_practice_attempt_and_update_memory", return_value=expected),
        ):
            result = submit_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
            )

        self.assertIs(result, expected)

    def test_submit_attempt_sync_path_keeps_duplicate_result(self) -> None:
        expected = _submission_result().model_copy(update={"duplicate_submission": True})
        with (
            patch("app.application.practice.service.record_practice_attempt_and_update_memory", return_value=expected),
        ):
            result = submit_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
            )

        self.assertIs(result, expected)

    def test_submit_attempt_with_scheduler_returns_queued_without_sync_evaluation(self) -> None:
        scheduled: list[str] = []
        with (
            patch("app.domains.practice.attempts._find_existing_practice_attempt", return_value=None),
            patch(
                "app.domains.practice.attempts._create_practice_attempt",
                return_value=(
                    {"id": "legacy-attempt-1", "created_at": "2026-05-09T00:00:00Z"},
                    {"job_id": "job-1", "legacy_attempt_id": "legacy-attempt-1"},
                ),
            ),
            patch(
                "app.domains.practice.attempts._get_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": []},
            ),
            patch("app.domains.practice.attempts.evaluate_practice_answer") as evaluate_answer,
        ):
            result = submit_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
                schedule_finalizer=scheduled.append,
            )

        self.assertTrue(result.is_correct)
        self.assertEqual(result.analysis_status, "queued")
        self.assertIsNone(result.mastery_evaluation)
        self.assertEqual(scheduled, ["job-1"])
        evaluate_answer.assert_not_called()

    def test_background_finalizer_runs_mastery_update_without_dual_write(self) -> None:
        finalization = PracticeAttemptFinalization(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            quiz_item=_quiz_item(),
            selected_option="C",
            legacy_attempt={"id": "legacy-attempt-1", "created_at": "2026-05-09T00:00:00Z"},
        )
        completed = _submission_result().model_copy(update={"analysis_status": "completed"})
        with (
            patch("app.application.practice.service.finalize_practice_attempt_analysis", return_value=completed) as finalize,
        ):
            finalize_attempt_analysis(finalization)

        finalize.assert_called_once()
        self.assertIs(finalize.call_args.kwargs["graph_mastery_update"], update_graph_mastery_from_practice_attempt)

    def test_background_finalizer_job_rebuilds_finalization_from_legacy_attempt(self) -> None:
        completed = _submission_result().model_copy(update={"analysis_status": "completed"})
        legacy_attempt = {
            "id": "legacy-attempt-1",
            "user_id": "u1",
            "session_id": "s1",
            "subject_id": "network",
            "question_id": "q1",
            "question_snapshot": _quiz_item().model_dump(),
            "selected_option": "C",
            "is_correct": True,
            "knowledge_point": "HTTP",
            "created_at": "2026-05-09T00:00:00Z",
        }
        with (
            patch(
                "app.application.practice.service.claim_practice_attempt_finalization_job",
                return_value={"job_id": "job-1", "legacy_attempt_id": "legacy-attempt-1"},
            ) as claim,
            patch("app.application.practice.service.get_practice_attempt_record_by_id") as get_attempt,
            patch("app.application.practice.service.finalize_practice_attempt_analysis", return_value=completed) as finalize,
            patch("app.application.practice.service.complete_practice_attempt_finalization_job") as complete,
            patch("app.application.practice.service.fail_practice_attempt_finalization_job") as fail,
        ):
            from app.shared.schemas.contracts import PracticeAttemptRecord

            get_attempt.return_value = PracticeAttemptRecord.model_validate(legacy_attempt)
            status = finalize_attempt_analysis_job("job-1")

        self.assertEqual(status, "completed")
        claim.assert_called_once_with("job-1")
        get_attempt.assert_called_once_with("legacy-attempt-1")
        finalize.assert_called_once()
        complete.assert_called_once_with("job-1")
        fail.assert_not_called()

    def test_dual_write_disabled_does_not_touch_graph_repositories(self) -> None:
        with (
            patch.dict(os.environ, {"ENABLE_GRAPH_DUAL_WRITE": "false", "ENABLE_GRAPH_FACTS": "true"}, clear=False),
            patch("app.application.practice.graph_facts.build_graph_fact_repositories") as build_repos,
        ):
            maybe_dual_write_practice_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
                result=_submission_result(),
            )

        build_repos.assert_not_called()

    def test_dual_write_records_attempt_learning_events_and_runs_mastery_graph(self) -> None:
        repos = _FakeRepos()
        with (
            patch.dict(os.environ, {"ENABLE_GRAPH_DUAL_WRITE": "true", "ENABLE_GRAPH_FACTS": "true"}, clear=False),
            patch("app.application.practice.graph_facts.build_graph_fact_repositories", return_value=repos),
            patch("app.application.practice.graph_facts.build_mastery_graph", return_value=_FakeGraph()) as build_mastery,
        ):
            maybe_dual_write_practice_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
                result=_submission_result(),
            )

        self.assertEqual([event.event_type for event in repos.learning_events.events], ["practice_attempt_submitted", "attempt_scored"])
        self.assertEqual(len(repos.attempts.attempts), 1)
        self.assertEqual(repos.attempts.attempts[0]["concept_id"], "HTTP")
        self.assertTrue(repos.attempts.attempts[0]["attempt_id"].startswith("practice:"))
        self.assertEqual(repos.learning_events.events[0].payload["source_object_id"], repos.attempts.attempts[0]["attempt_id"])
        self.assertNotEqual(repos.learning_events.events[0].payload["source_object_id"], "q1")
        self.assertEqual(len(repos.graph_runs.started), 1)
        self.assertEqual(len(repos.graph_runs.finished), 1)
        build_mastery.assert_called_once_with(subject_id="data-structure")

    def test_dual_write_attempt_source_object_is_scoped_by_session(self) -> None:
        repos = _FakeRepos()
        with (
            patch.dict(os.environ, {"ENABLE_GRAPH_DUAL_WRITE": "true", "ENABLE_GRAPH_FACTS": "true"}, clear=False),
            patch("app.application.practice.graph_facts.build_graph_fact_repositories", return_value=repos),
            patch("app.application.practice.graph_facts.build_mastery_graph", return_value=_FakeGraph()),
        ):
            maybe_dual_write_practice_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
                result=_submission_result(),
            )
            maybe_dual_write_practice_attempt(
                user_id="u1",
                session_id="s2",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
                result=_submission_result(),
            )

        first_source = repos.learning_events.events[0].payload["source_object_id"]
        second_source = repos.learning_events.events[2].payload["source_object_id"]
        self.assertNotEqual(first_source, second_source)
        self.assertEqual(first_source, repos.attempts.attempts[0]["attempt_id"])
        self.assertEqual(second_source, repos.attempts.attempts[1]["attempt_id"])


if __name__ == "__main__":
    unittest.main()
