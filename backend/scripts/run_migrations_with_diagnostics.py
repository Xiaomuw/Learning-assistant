"""Run Alembic migrations with startup diagnostics for CloudRun-style deploys."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.db.database import get_sqlalchemy_database_url  # noqa: E402


DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_LOCK_TIMEOUT_MS = 10_000
DEFAULT_STATEMENT_TIMEOUT_MS = 90_000


def main() -> int:
    db_url = get_sqlalchemy_database_url()
    connect_timeout = _env_int(
        "ALEMBIC_CONNECT_TIMEOUT_SECONDS",
        DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )
    lock_timeout_ms = _env_int("ALEMBIC_LOCK_TIMEOUT_MS", DEFAULT_LOCK_TIMEOUT_MS)
    statement_timeout_ms = _env_int(
        "ALEMBIC_STATEMENT_TIMEOUT_MS",
        DEFAULT_STATEMENT_TIMEOUT_MS,
    )
    alembic_url = _with_connect_timeout(db_url, connect_timeout)

    print(
        "🧱 数据库迁移诊断 | "
        f"target={_describe_url(alembic_url)} | "
        f"connect_timeout={connect_timeout}s | "
        f"lock_timeout={lock_timeout_ms}ms | "
        f"statement_timeout={statement_timeout_ms}ms",
        flush=True,
    )

    previous_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = _merge_pgoptions(
        previous_pgoptions,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
    )
    os.environ["ALEMBIC_DATABASE_URL"] = alembic_url

    engine = create_engine(
        alembic_url,
        future=True,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": connect_timeout,
            "options": (
                f"-c lock_timeout={lock_timeout_ms} "
                f"-c statement_timeout={statement_timeout_ms}"
            ),
        },
    )

    try:
        config = _alembic_config()
        heads = ScriptDirectory.from_config(config).get_heads()
        print(f"🧱 Alembic target heads: {','.join(heads) or '<empty>'}", flush=True)
        _print_database_state(engine)
        command.upgrade(config, "head")
        _print_current_revisions(engine, prefix="✅ 数据库迁移完成")
        return 0
    except Exception as exc:  # noqa: BLE001 - startup diagnostics must not hide failures
        print("❌ 数据库迁移失败", flush=True)
        print(f"   type={type(exc).__name__}", flush=True)
        print(f"   detail={_sanitize(str(exc), db_url)}", flush=True)
        print(
            "   请检查 PostgreSQL 地址/白名单、vector 扩展权限、表锁等待，"
            "以及 alembic_version 是否可读写。",
            flush=True,
        )
        return 1
    finally:
        if previous_pgoptions is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_pgoptions
        engine.dispose()


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def _print_database_state(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        version = connection.execute(text("SELECT version()")).scalar_one()
        database, user = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        vector_ready = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()
        print(
            "🧱 PostgreSQL connected | "
            f"database={database} | user={user} | vector={bool(vector_ready)}",
            flush=True,
        )
        print(f"🧱 PostgreSQL version: {str(version).split(',', 1)[0]}", flush=True)
        _print_current_revisions_for_connection(connection, prefix="🧱 Alembic current")
        _print_activity_snapshot(connection)


def _print_current_revisions(engine, *, prefix: str) -> None:
    with engine.connect() as connection:
        _print_current_revisions_for_connection(connection, prefix=prefix)


def _print_current_revisions_for_connection(connection, *, prefix: str) -> None:
    inspector = inspect(connection)
    if "alembic_version" not in set(inspector.get_table_names()):
        print(f"{prefix}: <missing alembic_version>", flush=True)
        return
    revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    print(f"{prefix}: {','.join(str(item) for item in revisions) or '<empty>'}", flush=True)


def _print_activity_snapshot(connection) -> None:
    try:
        rows = connection.execute(
            text(
                """
                SELECT state, wait_event_type, wait_event, count(*) AS count
                FROM pg_stat_activity
                WHERE datname = current_database()
                GROUP BY state, wait_event_type, wait_event
                ORDER BY count DESC
                LIMIT 8
                """
            )
        ).all()
    except SQLAlchemyError as exc:
        print(f"⚠️  pg_stat_activity 不可读取: {type(exc).__name__}", flush=True)
        return

    if not rows:
        print("🧱 pg_stat_activity: <empty>", flush=True)
        return
    summary = "; ".join(
        f"state={state or '-'},wait={wait_type or '-'}/{wait or '-'},count={count}"
        for state, wait_type, wait, count in rows
    )
    print(f"🧱 pg_stat_activity: {summary}", flush=True)


def _with_connect_timeout(db_url: str, timeout: int) -> str:
    parts = urlsplit(db_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", str(timeout))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _describe_url(db_url: str) -> str:
    parts = urlsplit(db_url)
    username = parts.username or "-"
    hostname = parts.hostname or "-"
    port = f":{parts.port}" if parts.port else ""
    database = parts.path.lstrip("/") or "-"
    return f"{parts.scheme}://{username}:***@{hostname}{port}/{database}"


def _merge_pgoptions(
    current: str | None,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> str:
    options = (current or "").strip()
    additions = f"-c lock_timeout={lock_timeout_ms} -c statement_timeout={statement_timeout_ms}"
    return f"{options} {additions}".strip()


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"⚠️  {name}={raw!r} 不是整数，使用默认值 {default}", flush=True)
        return default
    return value if value > 0 else default


def _sanitize(message: str, db_url: str) -> str:
    sanitized = message.replace(db_url, _describe_url(db_url))
    password = urlsplit(db_url).password
    if password:
        sanitized = sanitized.replace(password, "***")
    return sanitized


if __name__ == "__main__":
    raise SystemExit(main())
