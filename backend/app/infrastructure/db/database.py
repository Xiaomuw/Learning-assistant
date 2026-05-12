"""
数据库连接与 Session 管理
=========================
统一管理 SQLAlchemy Engine / Session。
运行时仅支持 PostgreSQL。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数，当前值为 {raw_value!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} 必须大于等于 {minimum}，当前值为 {value}")
    return value


def _normalize_database_url(raw_url: str | None) -> str:
    if not raw_url:
        raise RuntimeError(
            "未配置 DATABASE_URL。PostgreSQL 已成为唯一支持的运行时数据库。"
        )

    normalized = raw_url.strip()
    if normalized.startswith("postgresql+psycopg://"):
        return normalized
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)

    raise RuntimeError(
        "DATABASE_URL 必须是 PostgreSQL DSN，例如 "
        "'postgresql+psycopg://user:password@127.0.0.1:5432/learning_assistant'"
    )


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
DATABASE_CONNECT_TIMEOUT_SECONDS = _env_int(
    "DATABASE_CONNECT_TIMEOUT_SECONDS",
    5,
    minimum=1,
)
DATABASE_LOCK_TIMEOUT_MS = _env_int("DATABASE_LOCK_TIMEOUT_MS", 10_000)
DATABASE_STATEMENT_TIMEOUT_MS = _env_int("DATABASE_STATEMENT_TIMEOUT_MS", 30_000)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


def _postgres_connect_args() -> dict[str, int | str]:
    return {
        "connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS,
        "options": (
            f"-c lock_timeout={DATABASE_LOCK_TIMEOUT_MS}ms "
            f"-c statement_timeout={DATABASE_STATEMENT_TIMEOUT_MS}ms"
        ),
    }


def _build_engine() -> Engine:
    return create_engine(
        DATABASE_URL,
        future=True,
        pool_pre_ping=True,
        connect_args=_postgres_connect_args(),
    )


engine = _build_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """统一的数据库会话上下文。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_database_backend() -> str:
    """返回当前数据库方言名称。"""
    return engine.dialect.name


def get_sqlalchemy_database_url() -> str:
    """返回 SQLAlchemy 使用的 PostgreSQL DSN。"""
    return DATABASE_URL


def get_langgraph_postgres_url() -> str:
    """
    返回 LangGraph/PostgresSaver 使用的原生 PostgreSQL DSN。
    若显式配置 LANGGRAPH_POSTGRES_URL，则优先使用该值。
    """
    raw_url = os.getenv("LANGGRAPH_POSTGRES_URL")
    if raw_url:
        raw_url = raw_url.strip()
        if raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", "postgresql://", 1)
        if raw_url.startswith("postgresql://"):
            return raw_url
        if raw_url.startswith("postgresql+psycopg://"):
            return raw_url.replace("postgresql+psycopg://", "postgresql://", 1)
        raise RuntimeError("LANGGRAPH_POSTGRES_URL 必须是 PostgreSQL DSN。")

    return DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def ensure_postgres_extensions() -> None:
    """确保 PGVector 依赖的 PostgreSQL 扩展存在。"""
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
