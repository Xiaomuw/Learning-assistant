from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.infrastructure.db.database import Base
from app.infrastructure.db.models import (
    GraphAttemptModel,
    GraphConceptModel,
    GraphQuestionItemModel,
    MasterySnapshotModel,
    PracticeAttemptModel,
    QuestionBankItemModel,
    UserKnowledgeStatModel,
)
from app.persistence.backfill_graph_facts import backfill_graph_facts


class _FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _HybridSession:
    def __init__(self, session: Session, legacy_rows: dict[type[Any], list[Any]]) -> None:
        self._session = session
        self._legacy_rows = legacy_rows

    def scalars(self, statement):
        entity = None
        descriptions = getattr(statement, "column_descriptions", None) or []
        if descriptions:
            entity = descriptions[0].get("entity")
        if entity in self._legacy_rows:
            return _FakeScalarResult(self._legacy_rows[entity])
        return self._session.scalars(statement)

    def get(self, model: type[Any], primary_key: Any) -> Any:
        return self._session.get(model, primary_key)

    def add(self, instance: Any) -> None:
        self._session.add(instance)


class _HybridSessionScope:
    def __init__(self, session_local, legacy_rows: dict[type[Any], list[Any]]) -> None:
        self._session_local = session_local
        self._legacy_rows = legacy_rows
        self._session: Session | None = None

    def __enter__(self) -> _HybridSession:
        self._session = self._session_local()
        return _HybridSession(self._session, self._legacy_rows)

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._session is not None
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()


class GraphFactsBackfillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.tables = [
            GraphAttemptModel.__table__,
            MasterySnapshotModel.__table__,
            GraphQuestionItemModel.__table__,
            GraphConceptModel.__table__,
        ]
        Base.metadata.create_all(bind=self.engine, tables=self.tables)
        now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
        self.legacy_rows = {
            PracticeAttemptModel: [
                SimpleNamespace(
                    id="pa-1",
                    user_id="u1",
                    session_id="s1",
                    subject_id="network",
                    question_id="qb-1",
                    question_snapshot={"stem": "HTTP 默认端口是什么？"},
                    selected_option="A",
                    is_correct=True,
                    knowledge_point="HTTP 默认端口",
                    source_type="question_bank",
                    created_at=now,
                )
            ],
            UserKnowledgeStatModel: [
                SimpleNamespace(
                    user_id="u1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    exposure_count=3,
                    attempt_count=2,
                    correct_count=1,
                    wrong_count=1,
                    mastery_score=82.0,
                    mastery_level="learning",
                    last_seen_at=now,
                    last_practiced_at=now,
                    updated_at=now,
                )
            ],
            QuestionBankItemModel: [
                SimpleNamespace(
                    id="qb-1",
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    stem="HTTP 的默认端口是什么？",
                    options_json=[{"key": "A", "text": "80"}, {"key": "B", "text": "443"}],
                    correct_option="A",
                    explanation="HTTP 默认使用 80 端口。",
                    option_rationales_json={"A": "正确", "B": "HTTPS 常用端口"},
                    source_name="legacy-bank",
                    source_year=2026,
                    difficulty="基础",
                    tags_json=["network"],
                ),
                SimpleNamespace(
                    id="curriculum:" + "x" * 120,
                    subject_id="network",
                    knowledge_point="HTTP 默认端口",
                    stem="哪一个端口常用于 HTTP？",
                    options_json=[{"key": "A", "text": "80"}, {"key": "B", "text": "443"}],
                    correct_option="A",
                    explanation="HTTP 默认端口是 80。",
                    option_rationales_json={"A": "正确", "B": "HTTPS 常用端口"},
                    source_name="legacy-bank",
                    source_year=2026,
                    difficulty="基础",
                    tags_json=["network"],
                )
            ],
        }

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine, tables=self.tables)
        self.engine.dispose()

    def session_scope(self):
        return _HybridSessionScope(self.SessionLocal, self.legacy_rows)

    def test_dry_run_counts_operations_without_writing_graph_facts(self) -> None:
        result = backfill_graph_facts(execute=False, session_factory=self.session_scope)

        self.assertTrue(result.dry_run)
        self.assertGreaterEqual(result.dry_run_count, 3)
        self.assertEqual(result.inserted_count, 0)
        with self.SessionLocal() as session:
            self.assertEqual(len(session.scalars(select(GraphAttemptModel)).all()), 0)
            self.assertEqual(len(session.scalars(select(MasterySnapshotModel)).all()), 0)
            self.assertEqual(len(session.scalars(select(GraphQuestionItemModel)).all()), 0)
            self.assertEqual(len(session.scalars(select(GraphConceptModel)).all()), 0)

    def test_execute_backfills_graph_facts_and_is_idempotent(self) -> None:
        first = backfill_graph_facts(execute=True, session_factory=self.session_scope)
        second = backfill_graph_facts(execute=True, session_factory=self.session_scope)

        self.assertFalse(first.dry_run)
        self.assertEqual(first.error_count, 0)
        self.assertGreaterEqual(first.inserted_count, 4)
        self.assertGreaterEqual(second.skipped_count, 3)
        with self.SessionLocal() as session:
            attempt = session.get(GraphAttemptModel, "legacy-practice-pa-1")
            question = session.get(GraphQuestionItemModel, "legacy-question-qb-1")
            questions = session.scalars(select(GraphQuestionItemModel)).all()
            concepts = session.scalars(select(GraphConceptModel)).all()
            snapshots = session.scalars(select(MasterySnapshotModel)).all()

        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.score, 1.0)
        self.assertTrue(attempt.is_correct)
        self.assertIsNotNone(question)
        self.assertEqual(question.answer_key["correct_option"], "A")
        self.assertEqual(question.answer_key["correct_option_text"], "80")
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(len(item.id) <= 100 for item in questions))
        self.assertEqual(len(concepts), 1)
        self.assertEqual(len(snapshots), 1)
        self.assertAlmostEqual(snapshots[0].p_mastery, 0.82)
        self.assertEqual(
            snapshots[0].id,
            "legacy-knowledge-u1-computer-network-computer-network.application.http-https",
        )
        self.assertEqual(snapshots[0].concept_id, "computer-network.application.http-https")


if __name__ == "__main__":
    unittest.main()
