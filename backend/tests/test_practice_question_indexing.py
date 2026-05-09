from __future__ import annotations

import importlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.services.rag.indexing import index_practice_questions
from app.services.rag.loader import practice_question_to_document


CONCEPT_ID = "data-structure.binary-tree.traversal"


def _valid_item(**overrides):
    item = {
        "question_id": "pq-binary-tree-001",
        "subject_id": "data-structure",
        "concept_id": CONCEPT_ID,
        "concept_name": "二叉树遍历",
        "difficulty": "basic",
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


class PracticeQuestionIndexingTest(unittest.TestCase):
    def test_practice_question_to_document_builds_content_and_metadata(self) -> None:
        document = practice_question_to_document(_valid_item())

        self.assertIn("某二叉树的前序遍历", document.content)
        self.assertIn("A. A", document.content)
        self.assertIn("答案：A", document.content)
        self.assertIn("前序遍历先访问根结点", document.content)
        self.assertIn("知识点：前序遍历", document.content)
        self.assertIn("把前序遍历和中序遍历混淆", document.content)
        self.assertEqual(document.metadata["source_table"], "practice_question")
        self.assertEqual(document.metadata["doc_type"], "question_bank")
        self.assertEqual(document.metadata["source_id"], "pq-binary-tree-001")
        self.assertEqual(document.metadata["question_id"], "pq-binary-tree-001")
        self.assertEqual(document.metadata["concept_id"], CONCEPT_ID)
        self.assertEqual(document.metadata["concept_name"], "二叉树遍历")
        self.assertEqual(document.metadata["difficulty"], "basic")
        self.assertEqual(document.metadata["subject_id"], "data-structure")

    def test_index_practice_questions_groups_by_subject(self) -> None:
        items = [
            _valid_item(question_id="pq-ds-1", subject_id="data-structure"),
            _valid_item(question_id="pq-net-1", subject_id="computer-network"),
            _valid_item(question_id="pq-net-2", subject_id="computer-network"),
        ]

        with patch("app.services.rag.indexing.index_documents", side_effect=[1, 2]) as mocked_index:
            written = index_practice_questions(items)

        self.assertEqual(written, 3)
        self.assertEqual(mocked_index.call_count, 2)
        calls_by_subject = {
            call.kwargs["subject_id"]: call.kwargs["documents"]
            for call in mocked_index.call_args_list
        }
        self.assertEqual(len(calls_by_subject["data-structure"]), 1)
        self.assertEqual(len(calls_by_subject["computer-network"]), 2)

    def test_script_dry_run_reads_but_does_not_index(self) -> None:
        script = importlib.import_module("scripts.index_practice_questions")
        stdout = io.StringIO()

        with (
            patch.object(script, "init_database"),
            patch.object(script, "load_practice_questions", return_value=[_valid_item()]) as mocked_load,
            patch.object(script, "index_practice_questions") as mocked_index,
            redirect_stdout(stdout),
        ):
            exit_code = script.main(
                [
                    "--subject-id",
                    "data-structure",
                    "--concept-id",
                    CONCEPT_ID,
                    "--limit",
                    "5",
                    "--dry-run",
                ]
            )

        self.assertEqual(exit_code, 0)
        mocked_load.assert_called_once_with(
            subject_id="data-structure",
            concept_id=CONCEPT_ID,
            limit=5,
        )
        mocked_index.assert_not_called()
        self.assertIn("dry-run", stdout.getvalue())
        self.assertIn("读取 1 道 practice_question", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
