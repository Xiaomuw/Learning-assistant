from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.config.validation import (  # noqa: E402
    EnvironmentValidationError,
    collect_environment_warnings,
    validate_startup_environment,
)


class EnvironmentValidationTest(unittest.TestCase):
    def test_validate_startup_environment_accepts_postgres_and_strong_jwt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
            },
            clear=True,
        ):
            validate_startup_environment()

    def test_validate_startup_environment_rejects_mysql(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "mysql+pymysql://user:pass@127.0.0.1:3306/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("PostgreSQL", str(ctx.exception))

    def test_validate_startup_environment_rejects_placeholder_jwt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "replace-with-a-32-byte-or-longer-secret",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("JWT_SECRET_KEY", str(ctx.exception))

    def test_collect_environment_warnings_reports_optional_capabilities(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "LANGSMITH_TRACING": "true",
                "MCP_ENABLED": "true",
            },
            clear=True,
        ):
            warnings = collect_environment_warnings()

        self.assertTrue(any("MODEL_ACCESS_KEY" in item for item in warnings))
        self.assertTrue(any("SMTP" in item for item in warnings))
        self.assertTrue(any("LANGSMITH_API_KEY" in item for item in warnings))
        self.assertTrue(any("MCP_WEB_SERVER_URL" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
