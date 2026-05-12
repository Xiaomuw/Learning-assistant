from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.user_data.service import get_learning_center
from app.interfaces.api.user_data import router as user_data_router
from app.interfaces.auth.dependencies import verify_user_access
from app.infrastructure.db.database import Base
from app.infrastructure.db.models import (
    GraphAttemptModel,
    GraphQuestionItemModel,
    KbChapterModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
    MasterySnapshotModel,
    PracticeAttemptModel,
    PracticeQuestionModel,
    UserKnowledgeStatModel,
)
from app.shared.schemas.contracts import AuthUserView


class LearningCenterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.tables = [
            KbSubjectModel.__table__,
            KbChapterModel.__table__,
            KbTopicModel.__table__,
            KbConceptModel.__table__,
            MasterySnapshotModel.__table__,
            GraphAttemptModel.__table__,
            GraphQuestionItemModel.__table__,
            PracticeAttemptModel.__table__,
            PracticeQuestionModel.__table__,
            UserKnowledgeStatModel.__table__,
        ]
        Base.metadata.create_all(bind=self.engine, tables=self.tables)
        self.session_patch = patch(
            "app.domains.learning_center.service.session_scope",
            self.session_scope,
        )
        self.session_patch.start()
        app = FastAPI()
        app.include_router(user_data_router, prefix="/api")
        app.dependency_overrides[verify_user_access] = lambda: AuthUserView(
            id="u1",
            email="u1@example.com",
            display_name="测试用户",
            status="active",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.session_patch.stop()
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

    def test_empty_snapshots_still_return_full_registry_taxonomy(self) -> None:
        result = get_learning_center("u1")

        subject_ids = {subject.subject_id for subject in result.subjects}
        self.assertEqual(
            subject_ids,
            {"data-structure", "computer-network", "operating-system", "computer-organization"},
        )
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")
        self.assertEqual(traversal.status, "unstarted")
        self.assertEqual(traversal.p_mastery, 0.0)
        self.assertFalse(traversal.tested)
        self.assertEqual(traversal.test_status, "untested")
        self.assertEqual(traversal.attempt_count, 0)
        self.assertEqual(traversal.question_count, 0)
        data_structure = _find_subject(result, "data-structure")
        self.assertEqual(data_structure.tested_count, 0)
        self.assertEqual(data_structure.attempt_count, 0)
        self.assertEqual(data_structure.correct_count, 0)
        self.assertEqual(data_structure.wrong_count, 0)

    def test_partial_db_taxonomy_still_returns_full_registry_subjects(self) -> None:
        self._seed_minimal_taxonomy()

        result = get_learning_center("u1")

        subject_ids = {subject.subject_id for subject in result.subjects}
        self.assertEqual(
            subject_ids,
            {"data-structure", "computer-network", "operating-system", "computer-organization"},
        )
        self.assertGreater(len(_find_subject(result, "data-structure").chapters), 1)
        self.assertIsNotNone(_find_concept(result, "computer-network.application.http-https"))

    def test_snapshot_attempts_and_question_counts_attach_and_aggregate(self) -> None:
        self._seed_minimal_taxonomy()
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        practiced_at = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        with self.session_scope() as session:
            session.add(
                MasterySnapshotModel(
                    id="snap-u1-c1",
                    user_id="u1",
                    subject_id="data-structure",
                    concept_id="data-structure.binary-tree.traversal",
                    p_mastery=0.8,
                    status="mastered",
                    updated_at=now,
                )
            )
            session.add_all(
                [
                    GraphAttemptModel(
                        id="attempt-1",
                        user_id="u1",
                        subject_id="data-structure",
                        concept_id="data-structure.binary-tree.traversal",
                        question_id="q1",
                        is_correct=True,
                        created_at=now,
                    ),
                    GraphAttemptModel(
                        id="attempt-2",
                        user_id="u1",
                        subject_id="data-structure",
                        concept_id="data-structure.binary-tree.traversal",
                        question_id="q2",
                        is_correct=False,
                        created_at=practiced_at,
                    ),
                ]
            )
            session.add_all(
                [
                    PracticeQuestionModel(
                        question_id="pq-1",
                        subject_id="data-structure",
                        concept_id="data-structure.binary-tree.traversal",
                    ),
                    PracticeQuestionModel(
                        question_id="pq-2",
                        subject_id="data-structure",
                        concept_id="data-structure.binary-tree.traversal",
                    ),
                    PracticeQuestionModel(
                        question_id="pq-3",
                        subject_id="data-structure",
                        concept_id="data-structure.binary-tree.threaded-tree",
                    ),
                    GraphQuestionItemModel(
                        id="gq-1",
                        user_id="u1",
                        subject_id="data-structure",
                        primary_concept_id="data-structure.binary-tree.traversal",
                        stem="二叉树遍历 graph-era 题",
                    ),
                    GraphQuestionItemModel(
                        id="gq-other-subject",
                        user_id="u1",
                        subject_id="computer-network",
                        primary_concept_id="data-structure.binary-tree.traversal",
                        stem="其他学科题不应计入 data-structure 过滤结果",
                    ),
                ]
            )

        result = get_learning_center("u1", subject_id="data-structure")
        subject = result.subjects[0]
        topic = _find_topic_for_concept(result, "data-structure.binary-tree.traversal")
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")
        threaded = _find_concept(result, "data-structure.binary-tree.threaded-tree")

        self.assertEqual(traversal.status, "mastered")
        self.assertEqual(traversal.p_mastery, 0.8)
        self.assertTrue(traversal.tested)
        self.assertEqual(traversal.test_status, "tested")
        self.assertEqual(traversal.attempt_count, 2)
        self.assertEqual(traversal.correct_count, 1)
        self.assertEqual(traversal.wrong_count, 1)
        self.assertEqual(traversal.question_count, 3)
        self.assertTrue(traversal.last_practiced_at.startswith("2026-01-02"))
        self.assertEqual(threaded.status, "unstarted")
        self.assertEqual(threaded.question_count, 1)
        self.assertEqual(topic.tested_count, 1)
        self.assertEqual(topic.attempt_count, 2)
        self.assertEqual(topic.correct_count, 1)
        self.assertEqual(topic.wrong_count, 1)
        self.assertEqual(topic.status_counts["mastered"], 1)
        self.assertGreaterEqual(topic.status_counts["unstarted"], 1)
        self.assertEqual(subject.tested_count, 1)
        self.assertEqual(subject.attempt_count, 2)
        self.assertEqual(subject.correct_count, 1)
        self.assertEqual(subject.wrong_count, 1)
        self.assertTrue(result.next_move.concept_id.startswith("data-structure."))
        self.assertNotEqual(result.next_move.concept_id, traversal.concept_id)
        self.assertEqual(result.facts_source, "graph")

    def test_attempt_without_snapshot_marks_tested_but_unstarted(self) -> None:
        self._seed_minimal_taxonomy()
        with self.session_scope() as session:
            session.add(
                GraphAttemptModel(
                    id="attempt-no-snapshot",
                    user_id="u1",
                    subject_id="data-structure",
                    concept_id="data-structure.binary-tree.traversal",
                    question_id="q1",
                    is_correct=True,
                    created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                )
            )

        result = get_learning_center("u1", subject_id="data-structure")
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")
        topic = _find_topic_for_concept(result, "data-structure.binary-tree.traversal")

        self.assertEqual(traversal.status, "unstarted")
        self.assertEqual(traversal.p_mastery, 0.0)
        self.assertTrue(traversal.tested)
        self.assertEqual(traversal.test_status, "tested")
        self.assertEqual(traversal.attempt_count, 1)
        self.assertEqual(traversal.correct_count, 1)
        self.assertEqual(traversal.wrong_count, 0)
        self.assertEqual(topic.tested_count, 1)
        self.assertEqual(topic.coverage_ratio, 0.0)

    def test_learning_center_api_route_returns_taxonomy(self) -> None:
        response = self.client.get("/api/users/u1/learning-center")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user_id"], "u1")
        self.assertEqual(len(payload["subjects"]), 4)
        self.assertEqual(payload["subjects"][0]["tested_count"], 0)

    def test_learning_center_does_not_read_legacy_user_knowledge_stats(self) -> None:
        self._seed_minimal_taxonomy()
        with self.session_scope() as session:
            session.add(
                UserKnowledgeStatModel(
                    user_id="u1",
                    subject_id="data-structure",
                    knowledge_point="data-structure.binary-tree.traversal",
                    concept_id="data-structure.binary-tree.traversal",
                    concept_name="二叉树遍历",
                    mastery_score=0.99,
                    mastery_level="mastered",
                    attempt_count=9,
                    correct_count=9,
                    wrong_count=0,
                )
            )

        result = get_learning_center("u1", subject_id="data-structure")
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")

        self.assertEqual(traversal.status, "unstarted")
        self.assertEqual(traversal.p_mastery, 0.0)
        self.assertEqual(traversal.attempt_count, 0)
        self.assertEqual(traversal.correct_count, 0)

    def test_learning_center_uses_legacy_fallback_when_graph_facts_disabled(self) -> None:
        self._seed_minimal_taxonomy()
        with self.session_scope() as session:
            session.add(
                UserKnowledgeStatModel(
                    user_id="u1",
                    subject_id="data-structure",
                    knowledge_point="data-structure.binary-tree.traversal",
                    concept_id="data-structure.binary-tree.traversal",
                    concept_name="二叉树遍历",
                    mastery_score=0.72,
                    mastery_level="learning",
                    attempt_count=1,
                    correct_count=1,
                    wrong_count=0,
                )
            )
            session.add(
                PracticeAttemptModel(
                    id="legacy-attempt-1",
                    user_id="u1",
                    session_id="s1",
                    subject_id="data-structure",
                    question_id="q1",
                    question_snapshot={},
                    selected_option="A",
                    is_correct=True,
                    knowledge_point="二叉树遍历",
                    concept_id="data-structure.binary-tree.traversal",
                    concept_name="二叉树遍历",
                )
            )

        with patch.dict(os.environ, {"ENABLE_GRAPH_FACTS": "false"}, clear=False):
            result = get_learning_center("u1", subject_id="data-structure")
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")

        self.assertEqual(result.facts_source, "legacy_fallback")
        self.assertEqual(traversal.status, "learning")
        self.assertEqual(traversal.p_mastery, 0.72)
        self.assertEqual(traversal.attempt_count, 1)
        self.assertEqual(traversal.correct_count, 1)

    def test_legacy_fallback_resolves_chinese_knowledge_point_to_canonical_concept(self) -> None:
        self._seed_minimal_taxonomy()
        with self.session_scope() as session:
            session.add(
                UserKnowledgeStatModel(
                    user_id="u1",
                    subject_id="data-structure",
                    knowledge_point="二叉树遍历",
                    concept_id="",
                    concept_name="",
                    mastery_score=68,
                    mastery_level="learning",
                )
            )
            session.add(
                PracticeAttemptModel(
                    id="legacy-attempt-cn",
                    user_id="u1",
                    session_id="s1",
                    subject_id="data-structure",
                    question_id="legacy-q-cn",
                    question_snapshot={},
                    selected_option="A",
                    is_correct=False,
                    knowledge_point="二叉树遍历",
                    concept_id="",
                    concept_name="",
                )
            )
            session.add(
                PracticeQuestionModel(
                    question_id="legacy-question-cn",
                    subject_id="data-structure",
                    subject_name="数据结构与算法",
                    chapter_name="树与二叉树",
                    topic_name="二叉树",
                    concept_id="",
                    concept_name="二叉树遍历",
                    difficulty="medium",
                    stem="二叉树遍历相关题目",
                    options_json={"A": "A", "B": "B", "C": "C", "D": "D"},
                    answer="A",
                    explanation="解析",
                )
            )

        with patch.dict(os.environ, {"ENABLE_GRAPH_FACTS": "false"}, clear=False):
            result = get_learning_center("u1", subject_id="data-structure")
        traversal = _find_concept(result, "data-structure.binary-tree.traversal")

        self.assertEqual(traversal.status, "learning")
        self.assertEqual(traversal.p_mastery, 0.68)
        self.assertEqual(traversal.attempt_count, 1)
        self.assertEqual(traversal.wrong_count, 1)
        self.assertEqual(traversal.question_count, 1)

    def _seed_minimal_taxonomy(self) -> None:
        with self.session_scope() as session:
            session.add(KbSubjectModel(subject_id="data-structure", subject_name="数据结构与算法"))
            session.add(
                KbChapterModel(
                    chapter_id="data-structure.tree",
                    subject_id="data-structure",
                    chapter_name="树与二叉树",
                    sort_order=1,
                )
            )
            session.add(
                KbTopicModel(
                    topic_id="data-structure.binary-tree",
                    subject_id="data-structure",
                    chapter_id="data-structure.tree",
                    topic_name="二叉树",
                    sort_order=1,
                )
            )
            session.add_all(
                [
                    KbConceptModel(
                        concept_id="data-structure.binary-tree.traversal",
                        subject_id="data-structure",
                        chapter_id="data-structure.tree",
                        topic_id="data-structure.binary-tree",
                        concept_name="二叉树遍历",
                        aliases_json=["前序遍历", "中序遍历"],
                        prerequisites_json=[],
                        importance="high",
                        exam_frequency="high",
                    ),
                    KbConceptModel(
                        concept_id="data-structure.binary-tree.threaded-tree",
                        subject_id="data-structure",
                        chapter_id="data-structure.tree",
                        topic_id="data-structure.binary-tree",
                        concept_name="线索二叉树",
                        aliases_json=["线索化"],
                        prerequisites_json=["data-structure.binary-tree.traversal"],
                        importance="high",
                        exam_frequency="medium",
                    ),
                ]
            )


def _find_concept(result, concept_id: str):
    for subject in result.subjects:
        for chapter in subject.chapters:
            for topic in chapter.topics:
                for concept in topic.concepts:
                    if concept.concept_id == concept_id:
                        return concept
    raise AssertionError(f"未找到 concept: {concept_id}")


def _find_subject(result, subject_id: str):
    for subject in result.subjects:
        if subject.subject_id == subject_id:
            return subject
    raise AssertionError(f"未找到 subject: {subject_id}")


def _find_topic_for_concept(result, concept_id: str):
    for subject in result.subjects:
        for chapter in subject.chapters:
            for topic in chapter.topics:
                if any(concept.concept_id == concept_id for concept in topic.concepts):
                    return topic
    raise AssertionError(f"未找到 concept 所在 topic: {concept_id}")


if __name__ == "__main__":
    unittest.main()
