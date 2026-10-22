from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
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

from app.application.notebooks import curriculum_seed  # noqa: E402
from app.application.notebooks.builtin_seed import (  # noqa: E402
    build_builtin_seed_payload,
    get_builtin_seed_chapters,
    list_builtin_seed_subject_ids,
)
from app.application.notebooks.curriculum_seed import (  # noqa: E402
    build_curriculum_question_items,
    build_curriculum_seed_payload,
    iter_curriculum_branches,
    iter_curriculum_learning_units,
)
from app.shared.schemas.contracts import NotebookKnowledgeStatus  # noqa: E402
from scripts.seed_builtin_notebook_vectors import run_seed  # noqa: E402


class BuiltinNotebookSeedTest(unittest.TestCase):
    def setUp(self) -> None:
        # Curriculum packs are private/untracked production data. Tests use
        # generated synthetic fixtures so a clean public clone is reproducible.
        temporary = tempfile.TemporaryDirectory(prefix="learning-assistant-curriculum-test-")
        self.addCleanup(temporary.cleanup)
        self.curriculum_dir = Path(temporary.name)
        patcher = patch.object(curriculum_seed, "CURRICULUM_DIR", self.curriculum_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._write_synthetic_package("408", branch_count=12)
        self._write_synthetic_package("math", branch_count=12)

    def _write_synthetic_package(self, package_id: str, *, branch_count: int) -> None:
        branches = []
        for index in range(branch_count):
            branches.append(
                {
                    "branch_key": f"{package_id}-synthetic-branch-{index}",
                    "branch_title": f"Synthetic concept {package_id}-{index}",
                    "knowledge_point": f"Synthetic knowledge point {package_id}-{index}",
                    "core_explanation": "Test-only explanation written for isolated unit tests.",
                    "exam_patterns": [
                        f"Synthetic pattern {index}-{pattern_index}"
                        for pattern_index in range(1, 4)
                    ],
                    "pitfalls": [f"Synthetic pitfall {index}"],
                    "mastery_checks": [
                        f"Synthetic mastery check {index}-{check_index}"
                        for check_index in range(1, 3)
                    ],
                }
            )
        payload = {
            "id": package_id,
            "title": f"Synthetic curriculum {package_id}",
            "default_source_name": "Original synthetic test fixture",
            "exam_scopes": ["synthetic-test-only"],
            "subjects": [
                {
                    "subject_id": "computer-organization",
                    "subject_name": "Synthetic test subject",
                    "chapters": [
                        {
                            "chapter_key": f"{package_id}-synthetic-chapter",
                            "chapter_title": f"Synthetic chapter {package_id}",
                            "branches": branches,
                        }
                    ],
                }
            ],
        }
        (self.curriculum_dir / f"{package_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_builtin_seed_payload_has_deterministic_chapter_metadata(self) -> None:
        subject_id = "computer-network"
        texts, metadatas = build_builtin_seed_payload(subject_id)

        self.assertEqual(len(texts), len(get_builtin_seed_chapters(subject_id)))
        self.assertGreaterEqual(len(texts), 5)
        self.assertIn("HTTP 默认端口是 80", "\n".join(texts))

        first_metadata = metadatas[0]
        self.assertEqual(first_metadata["subject_id"], subject_id)
        self.assertEqual(first_metadata["doc_type"], "chapter")
        self.assertEqual(first_metadata["source"], "seed:built_in")
        self.assertTrue(first_metadata["source_id"].startswith(f"seed:{subject_id}:"))
        self.assertTrue(first_metadata["knowledge_point"])

    def test_all_builtin_subjects_have_seed_content(self) -> None:
        subject_ids = list_builtin_seed_subject_ids()

        self.assertEqual(
            set(subject_ids),
            {
                "data-structure",
                "computer-network",
                "computer-organization",
                "operating-system",
            },
        )
        for subject_id in subject_ids:
            self.assertGreaterEqual(len(get_builtin_seed_chapters(subject_id)), 4)

    def test_curriculum_packages_build_documents_and_questions(self) -> None:
        branches = iter_curriculum_branches(["408", "math"])
        self.assertGreaterEqual(len(branches), 20)
        for branch in branches:
            self.assertTrue(branch["knowledge_point"])
            self.assertTrue(branch["core_explanation"])
            self.assertTrue(branch["exam_patterns"])
            self.assertTrue(branch["pitfalls"])
            self.assertTrue(branch["mastery_checks"])

        units = iter_curriculum_learning_units(["408", "math"])
        questions = build_curriculum_question_items(["408", "math"])
        self.assertGreaterEqual(len({unit["knowledge_point"] for unit in units}), 70)
        self.assertGreaterEqual(len(questions), 140)

        payload = build_curriculum_seed_payload(["408"], subject_ids={"computer-organization"})
        texts, metadatas = payload["computer-organization"]
        self.assertGreaterEqual(len(texts), 2)
        self.assertIn("doc_type", metadatas[0])
        self.assertEqual(metadatas[0]["subject_id"], "computer-organization")
        self.assertIn(metadatas[1]["doc_type"], {"chapter", "exam_pattern"})
        self.assertIn("exam_scope", metadatas[0])

        questions = build_curriculum_question_items(["408"], subject_ids={"computer-organization"})
        self.assertGreaterEqual(len(questions), 2)
        first_question = questions[0]
        self.assertEqual(first_question["subject_id"], "computer-organization")
        self.assertEqual(len(first_question["options"]), 4)
        self.assertEqual(first_question["correct_option"], "A")
        self.assertTrue(first_question["explanation"])
        self.assertEqual(set(first_question["option_rationales"].keys()), {"A", "B", "C", "D"})

    def test_dry_run_does_not_write_vectors(self) -> None:
        with (
            patch(
                "scripts.seed_builtin_notebook_vectors.list_subject_records",
                return_value=[SimpleNamespace(id="computer-network")],
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.get_notebook_knowledge_status",
                return_value=NotebookKnowledgeStatus(
                    subject_id="computer-network",
                    collection_name="learning_computer-network",
                    coverage_level="empty",
                ),
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.ingest_notebook_documents",
            ) as mocked_ingest,
        ):
            results = run_seed(subject_ids=["computer-network"], dry_run=True)

        self.assertEqual(results[0].status, "dry-run")
        mocked_ingest.assert_not_called()

    def test_curriculum_dry_run_does_not_write_vectors_or_questions(self) -> None:
        with (
            patch(
                "scripts.seed_builtin_notebook_vectors.list_subject_records",
                return_value=[SimpleNamespace(id="computer-organization")],
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.get_notebook_knowledge_status",
                return_value=NotebookKnowledgeStatus(
                    subject_id="computer-organization",
                    collection_name="learning_computer-organization",
                    coverage_level="empty",
                ),
            ),
            patch("scripts.seed_builtin_notebook_vectors.ingest_notebook_documents") as mocked_ingest,
            patch("scripts.seed_builtin_notebook_vectors.upsert_question_bank_item_records") as mocked_questions,
            patch("scripts.seed_builtin_notebook_vectors.index_question_bank_items") as mocked_index,
        ):
            results = run_seed(
                subject_ids=["computer-organization"],
                curriculum_ids=["408"],
                with_questions=True,
                dry_run=True,
            )

        statuses = [result.status for result in results]
        self.assertIn("dry-run-curriculum", statuses)
        mocked_ingest.assert_not_called()
        mocked_questions.assert_not_called()
        mocked_index.assert_not_called()

    def test_curriculum_seed_writes_questions_when_enabled(self) -> None:
        with (
            patch(
                "scripts.seed_builtin_notebook_vectors.list_subject_records",
                return_value=[SimpleNamespace(id="computer-organization")],
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.get_notebook_knowledge_status",
                return_value=NotebookKnowledgeStatus(
                    subject_id="computer-organization",
                    collection_name="learning_computer-organization",
                    coverage_level="empty",
                ),
            ),
            patch("scripts.seed_builtin_notebook_vectors.ingest_notebook_documents", return_value=7),
            patch(
                "scripts.seed_builtin_notebook_vectors.upsert_question_bank_item_records",
                return_value=8,
            ) as mocked_questions,
            patch("scripts.seed_builtin_notebook_vectors.index_question_bank_items", return_value=8) as mocked_index,
        ):
            results = run_seed(
                subject_ids=["computer-organization"],
                curriculum_ids=["408"],
                with_questions=True,
                force=True,
            )

        self.assertIn("seeded-curriculum", [result.status for result in results])
        self.assertIn("seeded-questions", [result.status for result in results])
        question_payload = mocked_questions.call_args.args[0]
        self.assertGreaterEqual(len(question_payload), 2)
        self.assertEqual(len(question_payload[0]["options"]), 4)
        mocked_index.assert_called_once()

    def test_seed_skips_ready_notebook_without_force(self) -> None:
        with (
            patch(
                "scripts.seed_builtin_notebook_vectors.list_subject_records",
                return_value=[SimpleNamespace(id="computer-network")],
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.get_notebook_knowledge_status",
                return_value=NotebookKnowledgeStatus(
                    subject_id="computer-network",
                    collection_name="learning_computer-network",
                    doc_count=20,
                    coverage_score=80,
                    coverage_level="ready",
                    retrieval_ready=True,
                ),
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.ingest_notebook_documents",
            ) as mocked_ingest,
        ):
            results = run_seed(subject_ids=["computer-network"])

        self.assertEqual(results[0].status, "skipped")
        mocked_ingest.assert_not_called()

    def test_seed_writes_when_forced(self) -> None:
        with (
            patch(
                "scripts.seed_builtin_notebook_vectors.list_subject_records",
                return_value=[SimpleNamespace(id="computer-network")],
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.get_notebook_knowledge_status",
                return_value=NotebookKnowledgeStatus(
                    subject_id="computer-network",
                    collection_name="learning_computer-network",
                    doc_count=20,
                    coverage_score=80,
                    coverage_level="ready",
                    retrieval_ready=True,
                ),
            ),
            patch(
                "scripts.seed_builtin_notebook_vectors.ingest_notebook_documents",
                return_value=5,
            ) as mocked_ingest,
        ):
            results = run_seed(subject_ids=["computer-network"], force=True)

        self.assertEqual(results[0].status, "seeded")
        self.assertEqual(results[0].chunks, 5)
        mocked_ingest.assert_called_once()


if __name__ == "__main__":
    unittest.main()
