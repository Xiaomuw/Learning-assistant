from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs.mastery.adapter import (
    LegacyKnowledgeStatsMasteryRepository,
    LegacyPracticeAttemptRepository,
)
from app.orchestration.graphs.mastery.graph import build_graph
from app.orchestration.graphs.mastery.nodes import (
    _evidence_delta,
)
from app.orchestration.graphs.mastery.schemas import MasteryEvidence, SignalStrength
from app.orchestration.graphs.shared.schemas import FinalResponse, LearningEvent, LearningEventType
from app.shared.schemas.contracts import KnowledgeMasteryRecord


class MockMasterySnapshotRepository:
    def __init__(self, snapshots: list[dict] | None = None) -> None:
        self.snapshots = list(snapshots or [])
        self.upserts: list[dict] = []

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict]:
        return self.snapshots[:limit]

    def upsert_snapshot(self, payload: dict) -> str:
        self.upserts.append(payload)
        return f"snapshot-{len(self.upserts)}"


class MockLearningEventRepository:
    def __init__(self, events: list[LearningEvent] | None = None) -> None:
        self.events = list(events or [])

    def append(self, event: LearningEvent) -> str:
        self.events.append(event)
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        return [event for event in self.events if event.user_id == user_id][:limit]


class MockAttemptRepository:
    def __init__(self, attempts: list[dict] | None = None) -> None:
        self.attempts = list(attempts or [])
        self.created: list[dict] = []

    def create_attempt(self, payload: dict) -> str:
        self.created.append(payload)
        return str(payload.get("id") or payload.get("attempt_id") or f"attempt-{len(self.created)}")

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict]:
        return [attempt for attempt in self.attempts if attempt.get("user_id") == user_id][:limit]


class RaisingRepository:
    def append(self, event: LearningEvent) -> str:
        raise RuntimeError("append failed")

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        raise RuntimeError("learning event read failed")

    def create_attempt(self, payload: dict) -> str:
        raise RuntimeError("attempt write failed")

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict]:
        raise RuntimeError("attempt read failed")

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict]:
        raise RuntimeError("snapshot read failed")

    def upsert_snapshot(self, payload: dict) -> str:
        raise RuntimeError("snapshot write failed")


def _base_state(**overrides):
    state = {
        "run_id": "run-mastery",
        "user_id": "u1",
        "graph_type": "mastery",
        "source_policy": "open_tools",
    }
    state.update(overrides)
    return state


class MasteryGraphAdapterTest(unittest.TestCase):
    def test_graph_compiles_without_external_dependencies(self) -> None:
        result = build_graph().compile().invoke(_base_state(user_message="评估我的掌握度"))

        response = FinalResponse.model_validate(result["final_response"])
        self.assertIn("MasteryEvaluationGraph", response.answer)
        self.assertEqual(response.ui_payload["target_graph_type"], "mastery")

    def test_new_user_with_empty_repositories_has_no_mastery_update(self) -> None:
        result = build_graph(
            learning_event_repository=MockLearningEventRepository(),
            attempt_repository=MockAttemptRepository(),
            mastery_repository=MockMasterySnapshotRepository(),
        ).compile().invoke(_base_state(user_message="评估我的掌握度"))

        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(result.get("mastery_updates", []), [])
        self.assertEqual(result.get("mastery_snapshot_ids", []), [])
        self.assertIn("没有可消费", response.answer)

    def test_question_answer_event_from_repository_updates_mastery(self) -> None:
        event = LearningEvent(
            id="qa-event-1",
            event_type=LearningEventType.QUESTION_ANSWERED.value,
            user_id="u1",
            concept_id="HTTP",
            graph_run_id="run-qa",
            payload={
                "subject_id": "network",
                "concept_id": "HTTP",
                "score": 0.8,
                "confidence": 0.8,
            },
        )
        result = build_graph(
            learning_event_repository=MockLearningEventRepository([event]),
            mastery_repository=MockMasterySnapshotRepository(
                snapshots=[{"user_id": "u1", "subject_id": "network", "concept_id": "HTTP", "p_mastery": 0.45}]
            ),
        ).compile().invoke(_base_state())

        update = result["mastery_updates"][0]
        self.assertEqual(update["concept_id"], "HTTP")
        self.assertGreater(update["p_mastery"], update["previous_p_mastery"])
        self.assertEqual(update["consumed_signal_ids"], ["qa-event-1"])

    def test_practice_attempt_updates_mastery_and_persists_snapshot(self) -> None:
        repository = MockMasterySnapshotRepository(
            snapshots=[{"user_id": "u1", "concept_id": "HTTP 默认端口", "p_mastery": 0.5}]
        )
        result = build_graph(mastery_repository=repository).compile().invoke(
            _base_state(
                attempt_payloads=[
                    {
                        "attempt_id": "a1",
                        "user_id": "u1",
                        "subject_id": "network",
                        "knowledge_point": "HTTP 默认端口",
                        "is_correct": True,
                    }
                ]
            )
        )

        self.assertEqual(len(result["mastery_updates"]), 1)
        update = result["mastery_updates"][0]
        self.assertEqual(update["concept_id"], "HTTP 默认端口")
        self.assertGreater(update["p_mastery"], update["previous_p_mastery"])
        self.assertEqual(result["mastery_snapshot_ids"], ["snapshot-1"])
        self.assertEqual(repository.upserts[0]["status"], "learning")
        self.assertEqual(
            [event["event_type"] for event in result["output_learning_events"]],
            ["mastery_updated", "next_step_recommended"],
        )

    def test_attempt_repository_results_update_mastery(self) -> None:
        attempt_repo = MockAttemptRepository(
            attempts=[
                {
                    "attempt_id": "attempt-repo-1",
                    "user_id": "u1",
                    "subject_id": "network",
                    "knowledge_point": "HTTP 默认端口",
                    "is_correct": True,
                }
            ]
        )
        mastery_repo = MockMasterySnapshotRepository(
            snapshots=[{"user_id": "u1", "concept_id": "HTTP 默认端口", "p_mastery": 0.4}]
        )
        result = build_graph(
            attempt_repository=attempt_repo,
            mastery_repository=mastery_repo,
        ).compile().invoke(_base_state())

        update = result["mastery_updates"][0]
        self.assertEqual(update["concept_id"], "HTTP 默认端口")
        self.assertGreater(update["p_mastery"], 0.4)
        self.assertEqual(result["mastery_snapshot_ids"], ["snapshot-1"])

    def test_high_wrong_rate_lowers_mastery_and_marks_weak(self) -> None:
        result = build_graph().compile().invoke(
            _base_state(
                history_snapshots=[{"user_id": "u1", "concept_id": "数据库索引", "p_mastery": 0.75}],
                attempt_payloads=[
                    {
                        "attempt_id": f"wrong-{index}",
                        "user_id": "u1",
                        "subject_id": "db",
                        "knowledge_point": "数据库索引",
                        "is_correct": False,
                    }
                    for index in range(4)
                ],
            )
        )

        update = result["mastery_updates"][0]
        self.assertLess(update["p_mastery"], update["previous_p_mastery"])
        self.assertEqual(update["status"], "weak")

    def test_stale_history_creates_review_signal(self) -> None:
        old_time = (datetime.now(timezone.utc) - timedelta(days=75)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = build_graph().compile().invoke(
            _base_state(
                history_snapshots=[
                    {
                        "user_id": "u1",
                        "subject_id": "network",
                        "concept_id": "HTTP 缓存",
                        "p_mastery": 0.7,
                        "last_practiced_at": old_time,
                        "updated_at": old_time,
                    }
                ]
            )
        )

        update = result["mastery_updates"][0]
        self.assertEqual(update["concept_id"], "HTTP 缓存")
        self.assertLess(update["p_mastery"], update["previous_p_mastery"])
        self.assertTrue(update["consumed_signal_ids"][0].startswith("stale:u1:network:HTTP 缓存"))

    def test_weak_signal_does_not_override_strong_evidence_for_same_concept(self) -> None:
        strong = LearningEvent(
            id="event-strong",
            event_type="attempt_scored",
            user_id="u1",
            concept_id="HTTP",
            graph_run_id="run-q",
            payload={"subject_id": "network", "is_correct": True},
        )
        weak = LearningEvent(
            id="event-weak",
            event_type="insufficient_evidence",
            user_id="u1",
            concept_id="HTTP",
            graph_run_id="run-qa",
            payload={"subject_id": "network"},
        )

        result = build_graph().compile().invoke(
            _base_state(
                history_snapshots=[{"concept_id": "HTTP", "p_mastery": 0.5}],
                learning_events=[
                    strong.model_dump(mode="json"),
                    weak.model_dump(mode="json"),
                ],
            )
        )

        self.assertEqual(result["ignored_weak_signal_ids"], ["event-weak"])
        update = result["mastery_updates"][0]
        self.assertEqual(update["consumed_signal_ids"], ["event-strong"])
        self.assertGreater(update["p_mastery"], 0.5)

    def test_hint_lowers_positive_update(self) -> None:
        no_hint = MasteryEvidence(
            signal_id="a1",
            signal_source="attempt",
            user_id="u1",
            concept_id="HTTP",
            strength=SignalStrength.STRONG,
            observed_score=1.0,
        )
        with_hint = MasteryEvidence(
            signal_id="a2",
            signal_source="attempt",
            user_id="u1",
            concept_id="HTTP",
            strength=SignalStrength.STRONG,
            observed_score=1.0,
            hint_used=True,
            hint_count=2,
        )

        self.assertGreater(_evidence_delta(no_hint), _evidence_delta(with_hint))
        self.assertGreater(_evidence_delta(with_hint), 0)

    def test_bounded_update_clamps_p_mastery(self) -> None:
        result = build_graph().compile().invoke(
            _base_state(
                history_snapshots=[{"concept_id": "HTTP", "p_mastery": 0.95}],
                attempt_payloads=[
                    {
                        "attempt_id": f"a{i}",
                        "user_id": "u1",
                        "knowledge_point": "HTTP",
                        "is_correct": True,
                    }
                    for i in range(10)
                ],
            )
        )

        update = result["mastery_updates"][0]
        self.assertEqual(update["p_mastery"], 1.0)
        self.assertLessEqual(update["p_mastery"], 1.0)

    def test_consumed_signal_is_not_reprocessed(self) -> None:
        result = build_graph().compile().invoke(
            _base_state(
                consumed_signal_ids=["a1"],
                attempt_payloads=[
                    {
                        "attempt_id": "a1",
                        "user_id": "u1",
                        "knowledge_point": "HTTP",
                        "is_correct": True,
                    }
                ],
            )
        )

        self.assertEqual(result.get("mastery_updates", []), [])
        response = FinalResponse.model_validate(result["final_response"])
        self.assertIn("没有可消费", response.answer)

    def test_duplicate_attempt_id_is_consumed_once_per_run(self) -> None:
        attempt = {
            "attempt_id": "a1",
            "user_id": "u1",
            "knowledge_point": "HTTP",
            "is_correct": True,
        }
        result = build_graph().compile().invoke(
            _base_state(
                history_snapshots=[{"concept_id": "HTTP", "p_mastery": 0.5}],
                attempt_payloads=[attempt, dict(attempt)],
            )
        )

        self.assertEqual(len(result["aggregated_evidence"]), 1)
        self.assertEqual(result["mastery_updates"][0]["consumed_signal_ids"], ["a1"])

    def test_legacy_knowledge_stats_repository_maps_existing_records(self) -> None:
        record = KnowledgeMasteryRecord(
            user_id="u1",
            subject_id="network",
            knowledge_point="HTTP",
            exposure_count=2,
            attempt_count=1,
            correct_count=1,
            wrong_count=0,
            mastery_score=82.0,
            mastery_level="mastered",
        )
        with patch(
            "app.persistence.repositories.mastery.list_knowledge_mastery_records",
            return_value=[record],
        ):
            snapshots = LegacyKnowledgeStatsMasteryRepository().list_snapshots(user_id="u1")

        self.assertEqual(snapshots[0]["concept_id"], "HTTP")
        self.assertEqual(snapshots[0]["p_mastery"], 0.82)
        self.assertEqual(snapshots[0]["status"], "mastered")

    def test_legacy_knowledge_stats_repository_does_not_write_by_default(self) -> None:
        with patch("app.persistence.repositories.mastery.record_knowledge_exposure") as writer:
            snapshot_id = LegacyKnowledgeStatsMasteryRepository().upsert_snapshot(
                {
                    "user_id": "u1",
                    "subject_id": "network",
                    "concept_id": "HTTP",
                    "p_mastery": 0.7,
                    "status": "learning",
                }
            )

        self.assertEqual(snapshot_id, "u1:network:HTTP")
        writer.assert_not_called()

    def test_legacy_practice_attempt_repository_maps_existing_attempts(self) -> None:
        class FakeAttempt:
            id = "attempt-1"
            user_id = "u1"
            session_id = "s1"
            subject_id = "network"
            question_id = "q1"
            question_snapshot = {"question": "HTTP 默认端口是多少？"}
            selected_option = "C"
            is_correct = True
            knowledge_point = "HTTP 默认端口"
            source_type = "question_bank"
            created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        class FakeScalars:
            def all(self):
                return [FakeAttempt()]

        class FakeSession:
            def scalars(self, stmt):
                return FakeScalars()

        @contextmanager
        def fake_session_scope():
            yield FakeSession()

        with patch("app.persistence.repositories.mastery.session_scope", fake_session_scope):
            attempts = LegacyPracticeAttemptRepository(subject_id="network").list_recent_attempts(user_id="u1")

        self.assertEqual(attempts[0]["attempt_id"], "attempt-1")
        self.assertEqual(attempts[0]["concept_id"], "HTTP 默认端口")
        self.assertTrue(attempts[0]["is_correct"])

    def test_repository_read_exceptions_are_recorded_without_crashing(self) -> None:
        result = build_graph(
            learning_event_repository=RaisingRepository(),
            attempt_repository=RaisingRepository(),
            mastery_repository=RaisingRepository(),
        ).compile().invoke(_base_state())

        response = FinalResponse.model_validate(result["final_response"])
        codes = {error["code"] for error in result["errors"]}
        self.assertIn("mastery_learning_event_repository_error", codes)
        self.assertIn("mastery_attempt_repository_error", codes)
        self.assertIn("mastery_snapshot_repository_error", codes)
        self.assertEqual(result.get("mastery_updates", []), [])
        self.assertEqual(response.ui_payload["errors"], result["errors"])

    def test_repository_write_exception_is_recorded_without_crashing(self) -> None:
        result = build_graph(mastery_repository=RaisingRepository()).compile().invoke(
            _base_state(
                attempt_payloads=[
                    {
                        "attempt_id": "a1",
                        "user_id": "u1",
                        "subject_id": "network",
                        "knowledge_point": "HTTP",
                        "is_correct": True,
                    }
                ],
            )
        )

        self.assertEqual(result["mastery_snapshot_ids"], [])
        self.assertEqual(result["errors"][-1]["code"], "mastery_snapshot_repository_write_error")

    def test_mastery_graph_does_not_import_database_repositories_directly(self) -> None:
        graph_root = BACKEND_ROOT / "app" / "orchestration" / "graphs" / "mastery"
        forbidden = {
            "app.infrastructure.db.repositories",
            "session_scope",
            "PracticeAttemptModel",
            "UserKnowledgeStatModel",
        }
        for path in sorted(graph_root.glob("*.py")):
            content = path.read_text(encoding="utf-8")
            leaked = {symbol for symbol in forbidden if symbol in content}
            self.assertFalse(leaked, f"{path} leaked direct database access symbols: {leaked}")


if __name__ == "__main__":
    unittest.main()
