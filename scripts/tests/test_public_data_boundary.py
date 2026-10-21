"""Fast, dependency-free guardrails for the public repository's question-bank boundary.

This test checks committed-file shapes and examples. It does not audit Git
history, external copies, or the original legal rights of any material.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUESTION_DIR = ROOT / "data" / "practice_questions"
SAMPLE = ROOT / "examples" / "practice_questions.json"
REMOVED_BANKS = {
    "all_408.json",
    "data_structure.json",
    "operating_system.json",
    "computer_network.json",
    "computer_organization.json",
}


class PublicDataBoundaryTests(unittest.TestCase):
    def test_unverified_banks_are_absent_from_current_tree(self) -> None:
        self.assertTrue(QUESTION_DIR.is_dir())
        for name in REMOVED_BANKS:
            with self.subTest(name=name):
                self.assertFalse((QUESTION_DIR / name).exists())
        other_files = [
            path.relative_to(QUESTION_DIR).as_posix()
            for path in QUESTION_DIR.rglob("*")
            if path.is_file() and path.name != "README.md"
        ]
        self.assertEqual(other_files, [], "Question corpus files must stay out of the public tree")

    def test_synthetic_example_has_valid_standalone_json_shape(self) -> None:
        questions = json.loads(SAMPLE.read_text(encoding="utf-8"))
        self.assertIsInstance(questions, list)
        self.assertEqual(len(questions), 2)
        ids: set[str] = set()
        for item in questions:
            self.assertIsInstance(item, dict)
            self.assertTrue(str(item.get("question_id") or "").startswith("oss-demo-"))
            self.assertTrue(str(item.get("concept_id") or "").strip())
            self.assertTrue(str(item.get("stem") or "").strip())
            self.assertTrue(str(item.get("explanation") or "").strip())
            self.assertIn(item.get("difficulty"), {"basic", "medium", "hard"})
            options = item.get("options")
            self.assertIsInstance(options, dict)
            self.assertEqual(set(options), {"A", "B", "C", "D"})
            self.assertIn(item.get("answer"), options)
            self.assertNotIn(item["question_id"], ids)
            ids.add(item["question_id"])

    def test_private_question_locations_are_gitignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for marker in ("data/practice_questions/*", "data/private/", "data/imports/"):
            self.assertIn(marker, ignore)

    def test_maintenance_commands_have_no_removed_default_path(self) -> None:
        for relative in (
            "backend/scripts/rebuild_408_project_data.py",
            "backend/scripts/audit_408_questions.py",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                self.assertNotIn("data/practice_questions/all_408.json", content)
        rebuild = (ROOT / "backend/scripts/rebuild_408_project_data.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("questions_path: Path | None = None", rebuild)
        self.assertIn("if not options.dry_run", rebuild)


if __name__ == "__main__":
    unittest.main()
