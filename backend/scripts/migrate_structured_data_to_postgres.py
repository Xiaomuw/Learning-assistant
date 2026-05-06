from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TABLE_ORDER = [
    "subjects",
    "users",
    "user_profiles",
    "user_memories",
    "auth_refresh_tokens",
    "chat_sessions",
    "question_bank_items",
    "practice_attempts",
    "app_settings",
]

JSON_FIELDS = {
    "user_memories": {"weak_points", "error_count", "recent_topics"},
    "chat_sessions": {"messages", "latest_quiz", "session_memory"},
    "question_bank_items": {"options_json", "option_rationales_json", "tags_json"},
    "practice_attempts": {"question_snapshot"},
}

DATETIME_FIELDS = {
    "subjects": {"created_at"},
    "user_memories": {"updated_at"},
    "user_profiles": {"updated_at"},
    "users": {"created_at", "updated_at", "last_login_at"},
    "auth_refresh_tokens": {"expires_at", "revoked_at", "created_at", "last_used_at"},
    "chat_sessions": {"created_at", "updated_at"},
    "question_bank_items": {"created_at", "updated_at"},
    "practice_attempts": {"created_at"},
    "app_settings": {"updated_at"},
}


def _normalize_source_database_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if normalized.startswith("mysql://"):
        return normalized.replace("mysql://", "mysql+pymysql://", 1)
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


def _normalize_target_database_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql+psycopg://"):
        return normalized
    raise RuntimeError("target-url 必须是 PostgreSQL DSN。")


def _configure_target_env(target_url: str) -> None:
    normalized = _normalize_target_database_url(target_url)
    os.environ["DATABASE_URL"] = normalized
    os.environ.setdefault(
        "LANGGRAPH_POSTGRES_URL",
        normalized.replace("postgresql+psycopg://", "postgresql://", 1),
    )


def _load_target_modules():
    for module_name in [
        "app.infrastructure.db.repositories.bootstrap",
        "app.infrastructure.db.models",
        "app.infrastructure.db.database",
    ]:
        sys.modules.pop(module_name, None)

    db_database = importlib.import_module("app.infrastructure.db.database")
    db_models = importlib.import_module("app.infrastructure.db.models")
    db_bootstrap = importlib.import_module("app.infrastructure.db.repositories.bootstrap")
    return db_database, db_models, db_bootstrap


def _coerce_json_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return json.loads(stripped)
    return value


def _coerce_datetime_value(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _build_payload(
    table_name: str,
    raw_row: dict[str, Any],
    allowed_columns: set[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in raw_row.items():
        if key not in allowed_columns:
            continue
        if key in JSON_FIELDS.get(table_name, set()) and value is not None:
            value = _coerce_json_value(value)
        if key in DATETIME_FIELDS.get(table_name, set()) and value is not None:
            value = _coerce_datetime_value(value)
        payload[key] = value
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="将旧 MySQL / SQLite 结构化数据迁移到 PostgreSQL。")
    parser.add_argument("--source-url", required=True, help="源数据库 DSN，支持 mysql/sqlite/postgres。")
    parser.add_argument(
        "--target-url",
        default=os.getenv("DATABASE_URL", ""),
        help="目标 PostgreSQL DSN；默认读取当前环境 DATABASE_URL。",
    )
    args = parser.parse_args()

    if not args.target_url:
        raise RuntimeError("请通过 --target-url 或环境变量 DATABASE_URL 指定目标 PostgreSQL DSN。")

    source_engine = create_engine(_normalize_source_database_url(args.source_url), future=True)
    _configure_target_env(args.target_url)
    db_database, db_models, db_repositories = _load_target_modules()

    db_database.ensure_postgres_extensions()
    db_repositories.init_database()

    model_map = {
        "subjects": db_models.SubjectModel,
        "users": db_models.UserModel,
        "user_profiles": db_models.UserProfileModel,
        "user_memories": db_models.UserMemoryModel,
        "auth_refresh_tokens": db_models.AuthRefreshTokenModel,
        "chat_sessions": db_models.ChatSessionModel,
        "question_bank_items": db_models.QuestionBankItemModel,
        "practice_attempts": db_models.PracticeAttemptModel,
        "app_settings": db_models.AppSettingModel,
    }

    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    target_session_factory = db_database.SessionLocal

    report: dict[str, int] = {}
    with source_engine.connect() as source_connection, target_session_factory() as session:
        for table_name in TABLE_ORDER:
            if table_name not in metadata.tables:
                continue

            table = Table(table_name, metadata, autoload_with=source_engine)
            target_model = model_map[table_name]
            allowed_columns = {column.name for column in target_model.__table__.columns}

            rows = source_connection.execute(select(table)).mappings().all()
            for row in rows:
                payload = _build_payload(table_name, dict(row), allowed_columns)
                session.merge(target_model(**payload))
            report[table_name] = len(rows)

        session.commit()

    source_engine.dispose()

    print("Structured migration completed:")
    for table_name in TABLE_ORDER:
        if table_name in report:
            print(f"- {table_name}: {report[table_name]} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
