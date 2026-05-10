from __future__ import annotations

import asyncio
import importlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-startup-readiness-1234567890")

from app.infrastructure.db.readiness import DatabaseReadinessReport  # noqa: E402


class _CompiledGraph:
    def compile(self):
        return self


def _readiness_report() -> DatabaseReadinessReport:
    return DatabaseReadinessReport(
        database_backend="postgresql",
        alembic_heads=("head-revision",),
        alembic_current_revisions=("head-revision",),
        required_table_count=23,
        required_index_count=42,
        vector_extension_ready=True,
    )


async def _enter_lifespan(module) -> None:
    async with module.lifespan(module.app):
        return None


class StartupReadinessTest(unittest.TestCase):
    def test_public_fastapi_startup_uses_readonly_readiness_only(self) -> None:
        module = importlib.import_module("app.main")
        self._assert_startup_uses_readiness_only(module)

    def test_platform_sidecar_startup_uses_readonly_readiness_only(self) -> None:
        module = importlib.import_module("app.orchestration.platform.webapp")
        self._assert_startup_uses_readiness_only(module)

    def test_alembic_head_check_rejects_non_head_revision(self) -> None:
        readiness = importlib.import_module("app.infrastructure.db.readiness")
        with (
            patch.object(readiness, "_load_alembic_heads", return_value=("head-revision",)),
            patch.object(readiness, "_load_current_alembic_revisions", return_value=("old-revision",)),
        ):
            with self.assertRaisesRegex(RuntimeError, "Alembic revision 不在 head"):
                readiness.check_alembic_head()

    def test_bootstrap_script_defaults_to_dry_run(self) -> None:
        script = importlib.import_module("scripts.bootstrap_app_data")
        fake_report = {"dry_run": True, "confirm_required": "BOOTSTRAP_APP_DATA"}
        stdout = io.StringIO()
        with patch.object(script, "bootstrap_app_data", return_value=fake_report) as bootstrap, redirect_stdout(stdout):
            exit_code = script.main([])

        self.assertEqual(exit_code, 0)
        bootstrap.assert_called_once_with(confirm="")
        self.assertIn('"dry_run": true', stdout.getvalue())

    def _assert_startup_uses_readiness_only(self, module) -> None:
        fake_build_graph = Mock(return_value=_CompiledGraph())
        readiness = Mock(return_value=_readiness_report())

        with (
            patch.object(module, "validate_startup_environment") as validate_env,
            patch.object(module, "collect_environment_warnings", return_value=[]),
            patch.object(module, "assert_database_readiness", readiness),
            patch("app.orchestration.graphs.orchestrator.graph.build_graph", fake_build_graph),
            patch(
                "app.infrastructure.db.database.ensure_postgres_extensions",
                side_effect=AssertionError("startup must not create extensions"),
            ),
            patch(
                "app.infrastructure.db.repositories.bootstrap.init_database",
                side_effect=AssertionError("startup must not bootstrap database"),
            ),
            patch(
                "app.infrastructure.db.repositories.subjects.list_subject_records",
                side_effect=AssertionError("startup must not read bootstrap data"),
            ),
            patch(
                "app.services.rag.vector_store.ensure_vector_store_ready",
                side_effect=AssertionError("startup must not initialize PGVector collections"),
            ),
            patch(
                "app.infrastructure.llm.langsmith.initialize_langsmith",
                side_effect=AssertionError("startup should not initialize LangSmith client"),
            ),
            patch(
                "app.infrastructure.mcp.initialize_mcp",
                side_effect=AssertionError("startup should not initialize MCP client"),
            ),
        ):
            asyncio.run(_enter_lifespan(module))

        validate_env.assert_called_once_with()
        readiness.assert_called_once_with()
        fake_build_graph.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
