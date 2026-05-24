from __future__ import annotations

import json
import os
import sys
import tempfile
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

from app.infrastructure.db.models import UserMemoryModel, UserModel  # noqa: E402
import app.infrastructure.db.repositories._shared as shared_repositories  # noqa: E402


class _FakeSession:
    def __init__(self, *, user_exists: bool) -> None:
        self.user_exists = user_exists

    def get(self, model, _pk):
        if model is UserMemoryModel:
            return None
        if model is UserModel and self.user_exists:
            return SimpleNamespace(id=_pk)
        return None


class BootstrapLegacyMemoryTest(unittest.TestCase):
    def test_migrate_legacy_memories_skips_orphan_user_files(self) -> None:
        saved: list[str] = []

        @contextmanager
        def fake_session_scope():
            yield _FakeSession(user_exists=False)

        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "storage" / "data" / "memory"
            memory_dir.mkdir(parents=True)
            (memory_dir / "default_user.json").write_text(
                json.dumps({"weak_points": ["HTTP"]}),
                encoding="utf-8",
            )

            with (
                patch.object(shared_repositories, "session_scope", fake_session_scope),
                patch.object(shared_repositories, "Path", lambda value: Path(tmp) / value),
            ):
                migrated = shared_repositories.migrate_legacy_memories(
                    lambda user_id, _memory: saved.append(user_id)
                )

        self.assertEqual(migrated, 0)
        self.assertEqual(saved, [])

    def test_migrate_legacy_memories_keeps_existing_user_files(self) -> None:
        saved: list[str] = []

        @contextmanager
        def fake_session_scope():
            yield _FakeSession(user_exists=True)

        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "storage" / "data" / "memory"
            memory_dir.mkdir(parents=True)
            (memory_dir / "user-1.json").write_text(
                json.dumps({"weak_points": ["HTTP"], "recent_topics": ["DNS"]}),
                encoding="utf-8",
            )

            with (
                patch.object(shared_repositories, "session_scope", fake_session_scope),
                patch.object(shared_repositories, "Path", lambda value: Path(tmp) / value),
            ):
                migrated = shared_repositories.migrate_legacy_memories(
                    lambda user_id, _memory: saved.append(user_id)
                )

        self.assertEqual(migrated, 1)
        self.assertEqual(saved, ["user-1"])


if __name__ == "__main__":
    unittest.main()
