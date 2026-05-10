from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.infrastructure.db.database import Base
from app.infrastructure.db.models import (
    GraphConceptModel,
    GraphAttemptModel,
    GraphQuestionItemModel,
    GraphRunModel,
    LearningEventModel,
    MasterySnapshotModel,
    NodeRunModel,
    ToolRunModel,
)
from app.persistence.repositories.graph_facts import (
    CompositeAttemptRepository,
    SqlAttemptRepository,
    SqlConceptRepository,
    SqlGraphRunRepository,
    SqlLearningEventRepository,
    SqlMasterySnapshotRepository,
    SqlQuestionItemRepository,
    SqlToolRunRepository,
    _text,
)
from app.shared.schemas.agent_graphs import EvidenceChunk, LearningEvent, ToolCapability, ToolResult, ToolStatus


class FakeLegacyAttemptRepository:
    def __init__(self, attempts: list[dict[str, Any]]) -> None:
        self.attempts = attempts

    def create_attempt(self, payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("attempt_id") or "")

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        _ = limit
        return [item for item in self.attempts if item.get("user_id") == user_id]


class GraphPersistenceRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.tables = [
            GraphRunModel.__table__,
            NodeRunModel.__table__,
            ToolRunModel.__table__,
            LearningEventModel.__table__,
            GraphAttemptModel.__table__,
            MasterySnapshotModel.__table__,
            GraphQuestionItemModel.__table__,
            GraphConceptModel.__table__,
        ]
        Base.metadata.create_all(bind=self.engine, tables=self.tables)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine, tables=self.tables)
        self.engine.dispose()

    @contextmanager
    def session_scope(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def test_metadata_contains_graph_fact_tables_and_key_columns(self) -> None:
        table_names = {table.name for table in self.tables}
        self.assertEqual(
            table_names,
            {
                "graph_runs",
                "node_runs",
                "tool_runs",
                "learning_events",
                "attempts",
                "mastery_snapshots",
                "question_items",
                "concepts",
            },
        )
        self.assertIn("event_type", LearningEventModel.__table__.columns)
        self.assertIn("hash_key", LearningEventModel.__table__.columns)
        self.assertIn("capability", ToolRunModel.__table__.columns)
        self.assertIn("p_mastery", MasterySnapshotModel.__table__.columns)
        self.assertIn("langsmith_run_id", GraphRunModel.__table__.columns)
        self.assertIn("sampled", GraphRunModel.__table__.columns)
        self.assertIn("stem", GraphQuestionItemModel.__table__.columns)
        self.assertIn("name", GraphConceptModel.__table__.columns)

    def test_learning_event_repository_append_and_list_for_user(self) -> None:
        repo = SqlLearningEventRepository(session_factory=self.session_scope)
        event = LearningEvent(
            id="event-1",
            event_type="question_answered",
            user_id="u1",
            concept_id="HTTP",
            graph_run_id="run-1",
            payload={"score": 0.8, "answer": "不要保存完整答案"},
        )

        self.assertEqual(repo.append(event), "event-1")
        events = repo.list_for_user(user_id="u1", limit=10)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "question_answered")
        self.assertEqual(events[0].payload["score"], 0.8)
        self.assertNotIn("不要保存完整答案", str(events[0].payload))

    def test_learning_event_repository_deduplicates_by_hash_key(self) -> None:
        repo = SqlLearningEventRepository(session_factory=self.session_scope)
        first = LearningEvent(
            id="event-hash-1",
            event_type="question_answered",
            user_id="u1",
            graph_run_id="run-1",
            payload={"hash_key": "same-message-same-event", "score": 0.6},
        )
        second = first.model_copy(update={"id": "event-hash-2", "payload": {"hash_key": "same-message-same-event", "score": 0.9}})

        self.assertEqual(repo.append(first), "event-hash-1")
        self.assertEqual(repo.append(second), "event-hash-1")

        with self.session_scope() as session:
            rows = session.scalars(select(LearningEventModel)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].hash_key, "same-message-same-event")

    def test_graph_run_repository_records_run_and_audit_event(self) -> None:
        repo = SqlGraphRunRepository(session_factory=self.session_scope)
        graph_run_id = repo.start_run(
            {
                "run_id": "run-1",
                "graph_type": "qa",
                "run_name": "qagraph.shadow",
                "user_id": "u1",
                "inputs_summary": {"question": "敏感问题正文", "has_user_message": True},
            }
        )
        repo.record_audit_event(
            {
                "graph_run_id": graph_run_id,
                "node_name": "response_composer",
                "payload": {"answer": "敏感答案正文", "status": "ok"},
            }
        )
        repo.finish_run(graph_run_id, {"status": "completed", "latency_ms": 12, "outputs_summary": {"answer": "敏感答案"}})

        with self.session_scope() as session:
            run = session.get(GraphRunModel, graph_run_id)
            node_runs = session.scalars(select(NodeRunModel)).all()

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.latency_ms, 12)
        self.assertTrue(run.inputs_summary["has_user_message"])
        self.assertNotIn("敏感", str(run.inputs_summary))
        self.assertNotIn("敏感", str(run.outputs_summary))
        self.assertEqual(len(node_runs), 1)
        self.assertNotIn("敏感", str(node_runs[0].output_summary))

    def test_text_helper_truncates_within_requested_length(self) -> None:
        self.assertEqual(_text("short", 20), "short")
        self.assertEqual(_text("x" * 25, 20), f"{'x' * 17}...")
        self.assertEqual(len(_text("x" * 25, 20)), 20)
        self.assertEqual(_text("abcdef", 3), "abc")
        self.assertEqual(_text("abcdef", 2), "ab")
        self.assertEqual(_text("abcdef", 0), "")

    def test_graph_run_repository_clamps_request_mode_to_column_length(self) -> None:
        repo = SqlGraphRunRepository(session_factory=self.session_scope)
        graph_run_id = repo.start_run(
            {
                "run_id": "run-long-request-mode",
                "graph_type": "qa",
                "run_name": "qagraph.runtime",
                "status": "running",
                "request_mode": "sse-with-extra-debug-context",
            }
        )

        with self.session_scope() as session:
            run = session.get(GraphRunModel, graph_run_id)

        self.assertLessEqual(len(run.request_mode), 20)
        self.assertEqual(run.request_mode, "sse-with-extra-de...")

    def test_tool_run_repository_saves_only_summary_and_evidence_refs(self) -> None:
        repo = SqlToolRunRepository(session_factory=self.session_scope)
        result = ToolResult(
            tool_id="tool-1",
            provider="tavily",
            capability=ToolCapability.WEB_SEARCH,
            status=ToolStatus.SUCCESS,
            input_summary="HTTP/3 browser support",
            output={"document": "敏感网页正文", "doc_count": 1},
            evidence=[
                EvidenceChunk(
                    id="e1",
                    source_type="web",
                    source_id="https://example.com",
                    text="敏感 evidence 正文",
                    score=0.9,
                )
            ],
            latency_ms=33,
        )

        tool_run_id = repo.record_tool_run(result, graph_run_id="run-1")

        with self.session_scope() as session:
            row = session.get(ToolRunModel, tool_run_id)

        self.assertEqual(row.provider, "tavily")
        self.assertEqual(row.capability, ToolCapability.WEB_SEARCH.value)
        self.assertEqual(row.output_summary["doc_count"], 1)
        self.assertNotIn("敏感", str(row.output_summary))
        self.assertEqual(row.evidence_refs, [{"id": "e1", "source_type": "web", "source_id": "https://example.com", "score": 0.9}])

    def test_attempt_repository_and_composite_deduplicate_legacy_attempts(self) -> None:
        primary = SqlAttemptRepository(session_factory=self.session_scope)
        primary.create_attempt(
            {
                "attempt_id": "attempt-1",
                "user_id": "u1",
                "subject_id": "data-structure",
                "concept_id": "data-structure.binary-tree.traversal",
                "is_correct": True,
            }
        )
        composite = CompositeAttemptRepository(
            primary=primary,
            legacy=FakeLegacyAttemptRepository(
                [
                    {"attempt_id": "attempt-1", "user_id": "u1", "knowledge_point": "HTTP", "is_correct": False},
                    {"attempt_id": "legacy-2", "user_id": "u1", "knowledge_point": "TCP", "is_correct": True},
                ]
            ),
        )

        attempts = composite.list_recent_attempts(user_id="u1", limit=10)
        self.assertEqual([item["attempt_id"] for item in attempts], ["attempt-1", "legacy-2"])

    def test_mastery_snapshot_repository_upsert_keeps_unique_user_subject_concept(self) -> None:
        repo = SqlMasterySnapshotRepository(session_factory=self.session_scope)
        first_id = repo.upsert_snapshot(
            {
                "user_id": "u1",
                "subject_id": "data-structure",
                "concept_id": "data-structure.binary-tree.traversal",
                "p_mastery": 0.4,
                "status": "weak",
            }
        )
        second_id = repo.upsert_snapshot(
            {
                "user_id": "u1",
                "subject_id": "data-structure",
                "concept_id": "data-structure.binary-tree.traversal",
                "p_mastery": 0.7,
                "status": "learning",
            }
        )
        snapshots = repo.list_snapshots(user_id="u1", limit=10)

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["p_mastery"], 0.7)
        self.assertEqual(snapshots[0]["status"], "learning")

    def test_attempt_and_mastery_repositories_skip_non_canonical_concepts(self) -> None:
        attempt_repo = SqlAttemptRepository(session_factory=self.session_scope)
        mastery_repo = SqlMasterySnapshotRepository(session_factory=self.session_scope)

        self.assertEqual(
            attempt_repo.create_attempt(
                {
                    "attempt_id": "bad-attempt",
                    "user_id": "u1",
                    "subject_id": "general",
                    "concept_id": "http",
                    "is_correct": True,
                }
            ),
            "",
        )
        self.assertEqual(
            mastery_repo.upsert_snapshot(
                {"user_id": "u1", "subject_id": "general", "concept_id": "http", "p_mastery": 0.7}
            ),
            "",
        )

        with self.session_scope() as session:
            self.assertEqual(session.scalars(select(GraphAttemptModel)).all(), [])
            self.assertEqual(session.scalars(select(MasterySnapshotModel)).all(), [])

    def test_question_item_repository_persists_and_finds_similar_items(self) -> None:
        repo = SqlQuestionItemRepository(session_factory=self.session_scope)
        item_id = repo.create_question_item(
            {
                "id": "qitem-1",
                "user_id": "u1",
                "subject_id": "network",
                "primary_concept_id": "HTTP",
                "stem": "HTTP 的默认端口是什么？",
                "options": [{"key": "A", "text": "80"}],
                "answer_key": {"correct_option": "A"},
                "rubric": {"criteria": ["single_correct_option"]},
            }
        )

        matches = repo.find_similar({"stem": "HTTP 的默认端口是什么？"}, limit=5)

        self.assertEqual(item_id, "qitem-1")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], "qitem-1")
        self.assertEqual(matches[0]["primary_concept_id"], "HTTP")

    def test_question_item_similarity_scopes_by_user_and_subject_when_provided(self) -> None:
        repo = SqlQuestionItemRepository(session_factory=self.session_scope)
        repo.create_question_item(
            {
                "id": "qitem-u1",
                "user_id": "u1",
                "subject_id": "data-structure",
                "primary_concept_id": "stack",
                "stem": "栈这种数据结构最典型的访问规则是什么？",
                "options": [{"key": "A", "text": "后进先出"}],
                "answer_key": {"correct_option": "A"},
                "rubric": {"criteria": ["single_correct_option"]},
            }
        )

        same_user_matches = repo.find_similar(
            {
                "user_id": "u1",
                "subject_id": "data-structure",
                "stem": "栈这种数据结构最典型的访问规则是什么？",
            },
            limit=5,
        )
        other_user_matches = repo.find_similar(
            {
                "user_id": "u2",
                "subject_id": "data-structure",
                "stem": "栈这种数据结构最典型的访问规则是什么？",
            },
            limit=5,
        )

        self.assertEqual([item["id"] for item in same_user_matches], ["qitem-u1"])
        self.assertEqual(other_user_matches, [])

    def test_concept_repository_upserts_and_resolves_concept(self) -> None:
        repo = SqlConceptRepository(session_factory=self.session_scope)
        concept_id = repo.upsert_concept(
            {
                "concept_id": "http",
                "name": "HTTP",
                "subject_id": "network",
                "aliases": ["HyperText Transfer Protocol"],
                "source": "qagraph",
            }
        )
        resolved = repo.resolve_concept("HTTP")

        self.assertEqual(concept_id, "http")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["concept_id"], "http")
        self.assertEqual(resolved["aliases"], ["HyperText Transfer Protocol"])


if __name__ == "__main__":
    unittest.main()
