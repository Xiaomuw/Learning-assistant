from __future__ import annotations

import importlib
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)


@dataclass(frozen=True)
class _ImportResult:
    total: int
    inserted: int
    updated: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }


class Rebuild408ProjectDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = importlib.import_module("scripts.rebuild_408_project_data")

    def test_rebuild_defaults_to_dry_run_and_does_not_backup_or_import(self) -> None:
        with (
            patch.object(self.script, "_assert_alembic_current", return_value={"current_revision": "head"}),
            patch.object(self.script, "_taxonomy_health", return_value={"db_concept_count": 53}),
            patch.object(self.script, "_validate_question_file", return_value={"question_count": 530}),
            patch.object(self.script, "_cleanup_project_data", return_value={"tables": {}}) as cleanup,
            patch.object(self.script, "_backup_database") as backup,
            patch.object(self.script, "import_practice_questions") as import_questions,
        ):
            report = self.script.rebuild(self.script.RebuildOptions())

        self.assertTrue(report["dry_run"])
        cleanup.assert_called_once_with(dry_run=True)
        backup.assert_not_called()
        import_questions.assert_not_called()
        self.assertEqual(report["import"]["reason"], "dry_run")

    def test_confirmed_rebuild_backs_up_before_cleanup_and_import(self) -> None:
        order: list[str] = []

        def backup(_path):
            order.append("backup")
            return Path("/tmp/backup.dump")

        def cleanup(*, dry_run):
            order.append("cleanup")
            self.assertFalse(dry_run)
            return {"tables": {}}

        def import_questions(_raw, **_kwargs):
            order.append("import")
            return _ImportResult(total=530, inserted=530)

        with (
            patch.object(self.script, "_assert_alembic_current", return_value={"current_revision": self.script.EXPECTED_ALEMBIC_REVISION}),
            patch.object(self.script, "_taxonomy_health", return_value={"db_concept_count": 53}),
            patch.object(self.script, "_validate_question_file", return_value={"question_count": 530}),
            patch.object(self.script, "_backup_database", side_effect=backup),
            patch.object(self.script, "sync_knowledge_taxonomy", return_value=53),
            patch.object(self.script, "_cleanup_project_data", side_effect=cleanup),
            patch.object(self.script, "load_practice_question_json", return_value=[{"question_id": "q1"}]),
            patch.object(self.script, "import_practice_questions", side_effect=import_questions),
        ):
            report = self.script.rebuild(
                self.script.RebuildOptions(
                    confirm=self.script.CONFIRM_TOKEN,
                    import_questions=True,
                )
            )

        self.assertFalse(report["dry_run"])
        self.assertEqual(order, ["backup", "cleanup", "import"])
        self.assertEqual(report["import"]["inserted"], 530)

    def test_clear_table_scope_preserves_auth_users_and_taxonomy(self) -> None:
        clear_tables = set(self.script.STRUCTURED_CLEAR_TABLES)
        preserved = set(self.script.PRESERVED_TABLES)

        self.assertFalse(clear_tables & preserved)
        self.assertIn("practice_question", clear_tables)
        self.assertIn("mastery_snapshots", clear_tables)
        self.assertIn("learning_events", clear_tables)
        self.assertIn("kb_concept", preserved)
        self.assertIn("users", preserved)
        self.assertIn("auth_refresh_tokens", preserved)

    def test_backup_falls_back_to_jsonl_when_pg_dump_is_missing(self) -> None:
        with (
            patch.object(self.script.shutil, "which", return_value=None),
            patch.object(self.script, "_write_jsonl_backup", return_value=Path("/tmp/fallback.jsonl")) as fallback,
        ):
            path = self.script._backup_database(Path("/tmp/original.dump"))

        self.assertEqual(path, Path("/tmp/fallback.jsonl"))
        fallback.assert_called_once_with(Path("/tmp/original.jsonl"))


if __name__ == "__main__":
    unittest.main()
