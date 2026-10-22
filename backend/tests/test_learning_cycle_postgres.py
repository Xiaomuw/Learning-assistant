"""Real PostgreSQL + real compiled graphs; deterministic generator, no model API.

This deliberately tests graph/repository composition rather than repeating the
existing fake-repository tests. HTTP answer submission is a separate boundary.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__")

from tests.postgres_test_utils import TemporaryPostgresSchema
from app.infrastructure.db.database import Base
from app.infrastructure.db.models import (
    GraphQuestionItemModel, GraphAttemptModel, LearningEventModel, MasterySnapshotModel,
)
from app.persistence.repositories.graph_facts import (
    SqlQuestionItemRepository, SqlAttemptRepository, SqlLearningEventRepository, SqlMasterySnapshotRepository,
)
from app.orchestration.graphs.question_generation.graph import build_graph as question_graph
from app.orchestration.graphs.mastery.graph import build_graph as mastery_graph
from app.orchestration.graphs.question_generation.schemas import QuestionItem

CONCEPT = "computer-network.application.http-https"


class LearningCyclePostgresTest(unittest.TestCase):
    def setUp(self) -> None:
        schema = TemporaryPostgresSchema()
        schema.__enter__()
        self.addCleanup(schema.__exit__, None, None, None)
        self.engine = create_engine(schema.database_url)
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("select current_schema()")).scalar_one(), schema.schema)
        Base.metadata.create_all(self.engine, tables=[
            GraphQuestionItemModel.__table__, GraphAttemptModel.__table__,
            LearningEventModel.__table__, MasterySnapshotModel.__table__,
        ])
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session_scope(self):
        with self.sessions.begin() as session:
            yield session

    def test_generation_attempt_mastery_and_replay_use_persisted_facts(self) -> None:
        questions = SqlQuestionItemRepository(self.session_scope)
        events = SqlLearningEventRepository(self.session_scope)
        attempts = SqlAttemptRepository(self.session_scope)
        mastery = SqlMasterySnapshotRepository(self.session_scope)
        result = question_graph(question_item_repository=questions, learning_event_repository=events).compile().invoke({
            "run_id": "synthetic-qgen", "user_id": "synthetic-learner", "subject_id": "computer-network",
            "user_message": "帮我出题练习 HTTP 默认端口", "graph_type": "question_generation",
            "source_policy": "notebook_only", "difficulty": "基础", "count": 1,
            "concepts": [{"concept_id": CONCEPT, "name": "HTTP 默认端口"}],
            "evidence": [{"id": "original-fixture", "source_type": "notebook", "source_id": "synthetic-note",
                          "text": "HTTP 默认端口是 80，HTTPS 默认端口是 443。"}],
        })
        self.assertEqual(len(result["question_item_ids"]), 1)
        with self.session_scope() as session:
            saved = session.get(GraphQuestionItemModel, result["question_item_ids"][0])
            item = QuestionItem.model_validate({
                "id": saved.id, "stem": saved.stem, "options": saved.options_json,
                "answer_key": saved.answer_key, "rubric": saved.rubric,
                "primary_concept_id": saved.primary_concept_id,
                "source_refs": saved.source_refs, "difficulty": saved.difficulty,
            })
        self.assertEqual(item.primary_concept_id, CONCEPT)
        self.assertEqual(item.source_refs[0].evidence_id, "original-fixture")
        self.assertTrue(item.answer_key.correct_option_text)
        persisted_events = events.list_for_user(user_id="synthetic-learner")
        self.assertEqual({event.event_type for event in persisted_events}, {"question_reviewed", "question_generated"})
        self.assertEqual(events.list_for_user(user_id="other-learner"), [])

        attempt = {"attempt_id": "synthetic-attempt", "user_id": "synthetic-learner", "concept_id": CONCEPT,
                   "question_id": item.id, "is_correct": True, "score": 1.0}
        self.assertEqual(attempts.create_attempt(attempt), "synthetic-attempt")
        self.assertEqual(attempts.create_attempt(attempt), "synthetic-attempt")
        self.assertEqual(len(attempts.list_recent_attempts(user_id="synthetic-learner")), 1)
        self.assertEqual(attempts.list_recent_attempts(user_id="other-learner"), [])

        graph = mastery_graph(learning_event_repository=events, attempt_repository=attempts, mastery_repository=mastery).compile()
        state = {"run_id": "synthetic-mastery", "user_id": "synthetic-learner", "graph_type": "mastery",
                 "source_policy": "notebook_only"}
        first = graph.invoke(state)
        self.assertTrue(first["mastery_snapshot_ids"])
        snapshots = mastery.list_snapshots(user_id="synthetic-learner")
        self.assertEqual(len(snapshots), 1)
        self.assertGreater(snapshots[0]["p_mastery"], 0.5)
        self.assertTrue(snapshots[0]["consumed_signal_ids"])
        graph.invoke({**state, "run_id": "synthetic-replay"})
        replayed = mastery.list_snapshots(user_id="synthetic-learner")
        self.assertEqual(replayed[0]["p_mastery"], snapshots[0]["p_mastery"])
        self.assertEqual(mastery.list_snapshots(user_id="other-learner"), [])
        with self.session_scope() as session:
            self.assertEqual(len(session.scalars(select(GraphAttemptModel)).all()), 1)


if __name__ == "__main__":
    unittest.main()
