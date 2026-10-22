from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
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

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import KbChunkModel, KbSubjectModel  # noqa: E402
import app.infrastructure.db.repositories.knowledge_taxonomy as knowledge_taxonomy  # noqa: E402


class _FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def get(self, model, _pk):
        if model is KbSubjectModel:
            return None
        return SimpleNamespace()

    def add(self, _row) -> None:
        self.events.append("add_subject")

    def flush(self) -> None:
        self.events.append("flush")


class _FakeRegistry:
    subjects = {
        "computer-network": {
            "subject_id": "computer-network",
            "subject_name": "计算机网络",
            "source_file": "taxonomy.yml",
        }
    }

    def list_candidates(self, *, limit: int):
        return [
            SimpleNamespace(
                subject_id="computer-network",
                chapter_id="computer-network.transport-application",
                topic_id="computer-network.http",
                concept_id="computer-network.http.basic",
            )
        ]


class KnowledgeTaxonomyTest(unittest.TestCase):
    def test_shared_source_cleanup_preserves_personal_and_other_subject_rows(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        KbChunkModel.__table__.create(engine)

        @contextmanager
        def session_scope():
            with Session(engine) as session:
                yield session
                session.commit()

        with session_scope() as session:
            for row_id, subject, user in [
                ("shared", "computer-network", None),
                ("alice", "computer-network", "alice"),
                ("bob", "computer-network", "bob"),
                ("other-subject", "data-structure", None),
            ]:
                session.add(KbChunkModel(
                    id=row_id, subject_id=subject, source_file="synthetic.pdf",
                    metadata_json={"source_id": "synthetic.pdf", "doc_type": "pdf", "user_id": user},
                ))
        with patch.object(knowledge_taxonomy, "session_scope", session_scope):
            deleted = knowledge_taxonomy.delete_kb_chunks_by_source(
                subject_id="computer-network", source_file="synthetic.pdf",
                source_id="synthetic.pdf", doc_type="pdf", user_id=None,
            )
        self.assertEqual(deleted, 1)
        with session_scope() as session:
            self.assertEqual(set(session.scalars(select(KbChunkModel.id))), {"alice", "bob", "other-subject"})

    def test_flushes_taxonomy_rows_by_fk_dependency_order(self) -> None:
        events: list[str] = []

        @contextmanager
        def fake_session_scope():
            yield _FakeSession(events)

        def record(name: str):
            def inner(*_args, **_kwargs) -> None:
                events.append(name)

            return inner

        with (
            patch.object(knowledge_taxonomy, "session_scope", fake_session_scope),
            patch.object(knowledge_taxonomy, "_upsert_chapter", side_effect=record("chapter")),
            patch.object(knowledge_taxonomy, "_upsert_topic", side_effect=record("topic")),
            patch.object(knowledge_taxonomy, "_upsert_concept", side_effect=record("concept")),
        ):
            written = knowledge_taxonomy.sync_knowledge_taxonomy(_FakeRegistry())

        self.assertEqual(written, 4)
        self.assertEqual(
            events,
            [
                "add_subject",
                "flush",
                "chapter",
                "flush",
                "topic",
                "flush",
                "concept",
                "flush",
            ],
        )


if __name__ == "__main__":
    unittest.main()
