from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.postgres_test_utils import TemporaryPostgresSchema


CONCEPT_ID = "data-structure.binary-tree.traversal"


def _reload_or_import(module_name: str):
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def _valid_item(**overrides):
    item = {
        "question_id": "pq-binary-tree-001",
        "subject_id": "data-structure",
        "subject_name": "数据结构与算法",
        "chapter_name": "树与二叉树",
        "topic_name": "二叉树",
        "concept_id": CONCEPT_ID,
        "concept_name": "二叉树遍历",
        "difficulty": "基础",
        "stem": "某二叉树的前序遍历为 A B C，则根结点是哪个？",
        "options": {
            "A": "A",
            "B": "B",
            "C": "C",
            "D": "无法判断",
        },
        "answer": "A",
        "explanation": "前序遍历先访问根结点，因此根结点为 A。",
        "knowledge_points": ["前序遍历"],
        "common_trap": "把前序遍历和中序遍历混淆。",
    }
    item.update(overrides)
    return item


class PracticeQuestionImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._schema_context = TemporaryPostgresSchema()
        cls._schema_context.__enter__().configure_env()
        cls.db_database = _reload_or_import("app.infrastructure.db.database")
        _reload_or_import("app.infrastructure.db.models")
        cls.bootstrap = _reload_or_import("app.infrastructure.db.repositories.bootstrap")
        cls.repo = _reload_or_import("app.infrastructure.db.repositories.practice_questions")
        cls.db_database.ensure_postgres_extensions()
        cls.bootstrap.init_database()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._schema_context.__exit__(None, None, None)

    def test_validation_rejects_duplicate_question_id(self) -> None:
        result = self.repo.validate_practice_questions([_valid_item(), _valid_item()])

        self.assertFalse(result.valid)
        self.assertTrue(any(issue.field == "question_id" for issue in result.issues))

    def test_validation_rejects_missing_concept_and_invalid_required_fields(self) -> None:
        bad_item = _valid_item(
            question_id="pq-bad",
            concept_id="missing.concept",
            stem="",
            explanation="",
            difficulty="expert",
            answer="E",
            options={"A": "A", "B": "B", "C": "C"},
        )

        result = self.repo.validate_practice_questions([bad_item])

        self.assertFalse(result.valid)
        fields = {issue.field for issue in result.issues}
        self.assertTrue(
            {"concept_id", "stem", "explanation", "difficulty", "answer", "options"}.issubset(fields)
        )

    def test_validation_normalizes_valid_question(self) -> None:
        result = self.repo.validate_practice_questions([_valid_item()])

        self.assertTrue(result.valid, [issue.as_dict() for issue in result.issues])
        normalized = result.questions[0]
        self.assertEqual(normalized["difficulty"], "basic")
        self.assertEqual(normalized["concept_id"], CONCEPT_ID)
        self.assertEqual(normalized["concept_name"], "二叉树遍历")
        self.assertEqual(set(normalized["options"]), {"A", "B", "C", "D"})

    def test_import_supports_skip_and_upsert(self) -> None:
        first = self.repo.import_practice_questions([_valid_item()], on_conflict="skip")
        self.assertEqual(first.as_dict(), {"total": 1, "inserted": 1, "updated": 0, "skipped": 0})

        skipped = self.repo.import_practice_questions(
            [_valid_item(stem="已更新但应被跳过")],
            on_conflict="skip",
        )
        self.assertEqual(skipped.as_dict(), {"total": 1, "inserted": 0, "updated": 0, "skipped": 1})
        unchanged = self.repo.get_practice_question("pq-binary-tree-001")
        self.assertEqual(unchanged["stem"], "某二叉树的前序遍历为 A B C，则根结点是哪个？")

        updated = self.repo.import_practice_questions(
            [_valid_item(stem="已更新并应写入")],
            on_conflict="upsert",
        )
        self.assertEqual(updated.as_dict(), {"total": 1, "inserted": 0, "updated": 1, "skipped": 0})
        changed = self.repo.get_practice_question("pq-binary-tree-001")
        self.assertEqual(changed["stem"], "已更新并应写入")

    def test_practice_repository_reads_practice_question_before_legacy_bank(self) -> None:
        practice_repo = _reload_or_import("app.infrastructure.db.repositories.practice")
        self.repo.import_practice_questions(
            [_valid_item(question_id="pq-priority-001", stem="用于推荐的新题库题目")],
            on_conflict="upsert",
        )

        items = practice_repo.list_question_bank_item_records(
            subject_id="data-structure",
            knowledge_points=[CONCEPT_ID],
            limit=1,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].question_id, "pq-priority-001")
        self.assertEqual(items[0].source_name, "practice_question")
        self.assertEqual(items[0].concept_mapping_status, "matched")

    def test_synthetic_fixture_is_accepted_by_import_validator(self) -> None:
        path = BACKEND_ROOT.parent / "examples" / "practice_questions.json"
        raw_items = self.repo.load_practice_question_json(path)
        result = self.repo.validate_practice_questions(raw_items, source_file=str(path))

        self.assertTrue(result.valid, [issue.as_dict() for issue in result.issues[:5]])
        self.assertEqual(len(result.questions), 2)
        self.assertEqual(
            {item["question_id"] for item in result.questions},
            {"oss-demo-preorder-01", "oss-demo-preorder-02"},
        )
        self.assertEqual({item["concept_id"] for item in result.questions}, {CONCEPT_ID})
        self.assertTrue(all(item["difficulty"] == "basic" for item in result.questions))

    def test_rebuild_validator_accepts_small_authorized_fixture(self) -> None:
        # Regression: a permitted local corpus no longer needs exactly 530
        # questions, 53 concepts, or the old fixed difficulty distribution.
        rebuild = importlib.import_module("scripts.rebuild_408_project_data")
        path = BACKEND_ROOT.parent / "examples" / "practice_questions.json"
        summary = rebuild._validate_question_file(path)

        self.assertEqual(summary["question_count"], 2)
        self.assertEqual(summary["concept_count"], 1)
        self.assertEqual(summary["per_concept"], {"min": 2, "max": 2})
        self.assertEqual(
            summary["difficulty_distribution"], {"basic": 2, "medium": 0, "hard": 0}
        )


if __name__ == "__main__":
    unittest.main()
