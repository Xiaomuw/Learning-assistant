from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.postgres_test_utils import (
    PostgresTestConfigurationError,
    TemporaryPostgresDatabase,
    get_test_database_base_url,
)


class PostgresTestUtilsTest(unittest.TestCase):
    def test_strict_mode_requires_explicit_test_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POSTGRES_TEST_STRICT": "true",
                "DATABASE_URL": "postgresql+psycopg://user:pass@127.0.0.1:5432/app",
            },
            clear=False,
        ):
            os.environ.pop("TEST_DATABASE_URL", None)

            with self.assertRaises(PostgresTestConfigurationError) as raised:
                get_test_database_base_url()

        self.assertIn("未配置 TEST_DATABASE_URL", str(raised.exception))

    def test_non_strict_mode_missing_url_skips(self) -> None:
        with patch.dict(os.environ, {"POSTGRES_TEST_STRICT": "false"}, clear=False):
            os.environ.pop("TEST_DATABASE_URL", None)

            with self.assertRaises(unittest.SkipTest):
                get_test_database_base_url()

    def test_database_isolation_rejects_non_test_targets_before_connecting(self) -> None:
        for url in (
            "postgresql://user:pass@127.0.0.1/app",
            "postgresql://user:pass@remote.example.invalid/app_test",
            "postgresql://user:pass@127.0.0.1/app_test?options=-csearch_path=public",
        ):
            with self.subTest(url=url), patch.dict(os.environ, {"TEST_DATABASE_URL": url}):
                with patch("tests.postgres_test_utils.create_engine") as create_engine:
                    with self.assertRaises(PostgresTestConfigurationError):
                        TemporaryPostgresDatabase()
                    create_engine.assert_not_called()

    def test_postgres_url_is_normalized_to_psycopg_driver(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_DATABASE_URL": "postgres://user:pass@127.0.0.1:5432/app"},
            clear=False,
        ):
            self.assertEqual(
                get_test_database_base_url(),
                "postgresql+psycopg://user:pass@127.0.0.1:5432/app",
            )


if __name__ == "__main__":
    unittest.main()
