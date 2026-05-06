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

from app.application.practice.graph_facts import maybe_dual_write_practice_attempt
from app.application.practice.service import submit_attempt
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
    def test_submit_attempt_invokes_dual_write_hook_without_changing_result(self) -> None:
        expected = _submission_result()
        with (
            patch("app.application.practice.service.record_practice_attempt_and_update_memory", return_value=expected),
            patch("app.application.practice.service.maybe_dual_write_practice_attempt") as dual_write,
        ):
            result = submit_attempt(
                user_id="u1",
                session_id="s1",
                subject_id="network",
                quiz_item=_quiz_item(),
                selected_option="C",
            )

        self.assertIs(result, expected)
        dual_write.assert_called_once()

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
        self.assertEqual(len(repos.graph_runs.started), 1)
        self.assertEqual(len(repos.graph_runs.finished), 1)
        build_mastery.assert_called_once_with(subject_id="data-structure")


if __name__ == "__main__":
    unittest.main()
