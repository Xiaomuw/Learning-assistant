"""
数据库连接与 Session 管理
=========================
统一管理 SQLAlchemy Engine / Session。

默认支持 MySQL（推荐通过 DATABASE_URL 指向 MySQL），
若本地尚未配置 DATABASE_URL，则回退到 SQLite 以保证开发可运行。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _default_sqlite_url() -> str:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'learning_assistant.db').as_posix()}"


def _normalize_database_url(raw_url: str | None) -> str:
    if not raw_url:
        return _default_sqlite_url()

    if raw_url.startswith("mysql://"):
        return raw_url.replace("mysql://", "mysql+pymysql://", 1)

    return raw_url


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


def _build_engine() -> Engine:
    connect_args: dict[str, object] = {}
    if DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        DATABASE_URL,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
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

