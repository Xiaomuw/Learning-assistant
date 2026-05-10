from __future__ import annotations

import os
import unittest
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


STRICT_POSTGRES_ENV = "POSTGRES_TEST_STRICT"
_TRUE_VALUES = {"1", "true", "yes", "on"}


class PostgresTestConfigurationError(RuntimeError):
    """Raised when PostgreSQL integration tests are required but not configured."""


def _strict_postgres_required() -> bool:
    return os.getenv(STRICT_POSTGRES_ENV, "").strip().lower() in _TRUE_VALUES


def _postgres_config_error(message: str) -> None:
    if _strict_postgres_required():
        raise PostgresTestConfigurationError(message)
    raise unittest.SkipTest(f"{message}，跳过 PostgreSQL 集成测试。")


def _normalize_postgres_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if "__tests_only__" in normalized:
        _postgres_config_error("TEST_DATABASE_URL 包含占位符 __tests_only__")
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql+psycopg://"):
        return normalized
    _postgres_config_error("TEST_DATABASE_URL 必须是 PostgreSQL DSN")
    raise AssertionError("unreachable")


def get_test_database_base_url() -> str:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        _postgres_config_error("未配置 TEST_DATABASE_URL")
        raise AssertionError("unreachable")
    return _normalize_postgres_url(raw_url)


class TemporaryPostgresSchema:
    def __init__(self) -> None:
        self.base_url = get_test_database_base_url()
        self.schema = f"test_{uuid.uuid4().hex}"
        self.admin_engine = create_engine(self.base_url, future=True)
        self.database_url = ""
        self.langgraph_url = ""

    def __enter__(self):
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))

        url = make_url(self.base_url)
        query = dict(url.query)
        existing_options = str(query.get("options", "") or "").strip()
        search_path_option = f"-csearch_path={self.schema}"
        query["options"] = (
            f"{existing_options} {search_path_option}".strip()
            if existing_options
            else search_path_option
        )

        self.database_url = url.set(query=query).render_as_string(hide_password=False)
        self.langgraph_url = self.database_url.replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            with self.admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        finally:
            self.admin_engine.dispose()

    def configure_env(self) -> None:
        os.environ["DATABASE_URL"] = self.database_url
        os.environ["LANGGRAPH_POSTGRES_URL"] = self.langgraph_url
