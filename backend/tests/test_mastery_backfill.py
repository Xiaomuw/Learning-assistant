from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from scripts import backfill_mastery_snapshots


class MasteryBackfillTest(unittest.TestCase):
    def test_backfill_creates_graph_attempt_and_is_idempotent(self) -> None:
        existing_attempt_ids: set[str] = set()
        snapshots: list[dict] = []
        legacy_attempt = SimpleNamespace(
            id="legacy-attempt-1",
            user_id="u1",
            subject_id="computer-network",
            question_id="q-http",
            selected_option="C",
            is_correct=True,
            concept_id="computer-network.application.http-https",
            created_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
        )

        fake_repos = _FakeRepos(existing_attempt_ids)
        fake_graph = _FakeGraph(snapshots)
        with (
            patch.object(backfill_mastery_snapshots, "_legacy_attempts", return_value=[legacy_attempt]),
            patch.object(
                backfill_mastery_snapshots,
                "_graph_attempt_exists",
                side_effect=lambda attempt_id: attempt_id in existing_attempt_ids,
            ),
            patch.object(backfill_mastery_snapshots, "build_graph_fact_repositories", return_value=fake_repos),
            patch.object(backfill_mastery_snapshots, "build_mastery_graph", return_value=fake_graph),
        ):
            first = backfill_mastery_snapshots.backfill(user_id="u1")
            second = backfill_mastery_snapshots.backfill(user_id="u1")

        self.assertEqual(first["backfilled"], 1)
        self.assertEqual(first["skipped_existing"], 0)
        self.assertEqual(second["backfilled"], 0)
        self.assertEqual(second["skipped_existing"], 1)
        self.assertIn("practice:legacy-attempt-1", existing_attempt_ids)
        self.assertEqual(snapshots[0]["concept_id"], "computer-network.application.http-https")
        self.assertEqual(snapshots[0]["p_mastery"], 1.0)


class _FakeRepos:
    def __init__(self, existing_attempt_ids: set[str]):
        self.attempts = _FakeAttemptRepository(existing_attempt_ids)
        self.learning_events = object()
        self.mastery_snapshots = object()


class _FakeAttemptRepository:
    def __init__(self, existing_attempt_ids: set[str]):
        self.existing_attempt_ids = existing_attempt_ids

    def create_attempt(self, payload: dict) -> str:
        self.existing_attempt_ids.add(str(payload["id"]))
        return str(payload["id"])


class _FakeGraph:
    def __init__(self, snapshots: list[dict]):
        self.snapshots = snapshots

    def compile(self):
        return self

    def invoke(self, state: dict):
        payload = state["attempt_payloads"][0]
        self.snapshots.append(
            {
                "user_id": payload["user_id"],
                "subject_id": payload["subject_id"],
                "concept_id": payload["concept_id"],
                "p_mastery": payload["score"],
            }
        )
        return {}


if __name__ == "__main__":
    unittest.main()
