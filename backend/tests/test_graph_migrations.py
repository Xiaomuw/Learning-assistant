from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class GraphMigrationContractTest(unittest.TestCase):
    def test_alembic_baseline_files_exist_for_graph_facts(self) -> None:
        self.assertTrue((BACKEND_ROOT / "alembic.ini").exists())
        self.assertTrue((BACKEND_ROOT / "alembic" / "env.py").exists())
        revision = BACKEND_ROOT / "alembic" / "versions" / "0001_graph_facts.py"
        self.assertTrue(revision.exists())

        content = revision.read_text(encoding="utf-8")
        for table_name in (
            "graph_runs",
            "node_runs",
            "tool_runs",
            "learning_events",
            "attempts",
            "mastery_snapshots",
            "question_items",
            "concepts",
        ):
            self.assertIn(table_name, content)
        self.assertIn("langsmith_run_id", content)
        self.assertIn("sampled", content)

    def test_alembic_upgrade_head_on_empty_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "graph_facts.db"
            env = os.environ.copy()
            env["ALEMBIC_DATABASE_URL"] = f"sqlite:///{db_path}"
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=BACKEND_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            connection = sqlite3.connect(db_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()
            self.assertTrue(
                {
                    "graph_runs",
                    "node_runs",
                    "tool_runs",
                    "learning_events",
                    "attempts",
                    "mastery_snapshots",
                    "question_items",
                    "concepts",
                    "alembic_version",
                }.issubset(table_names)
            )


if __name__ == "__main__":
    unittest.main()
