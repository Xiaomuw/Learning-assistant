"""Dry-run or clean old authentication history rows."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

CONFIRM_TOKEN = "CLEANUP_AUTH_HISTORY"
DEFAULT_RETENTION_DAYS = 30


@dataclass(frozen=True)
class CleanupSpec:
    key: str
    table_name: str
    id_column: str
    value_column: str
    required_columns: tuple[str, ...]
    where_sql: str


AUTH_HISTORY_SPECS: tuple[CleanupSpec, ...] = (
    CleanupSpec(
        key="auth_refresh_tokens.expired_or_revoked",
        table_name="auth_refresh_tokens",
        id_column="id",
        value_column="token_jti",
        required_columns=("id", "token_jti", "expires_at", "revoked_at"),
        where_sql=(
            "(expires_at < :cutoff) "
            "OR (revoked_at IS NOT NULL AND revoked_at < :cutoff)"
        ),
    ),
    CleanupSpec(
        key="email_verification_challenges.expired_or_consumed",
        table_name="email_verification_challenges",
        id_column="id",
        value_column="email",
        required_columns=("id", "email", "expires_at", "consumed_at"),
        where_sql=(
            "(expires_at < :cutoff) "
            "OR (consumed_at IS NOT NULL AND consumed_at < :cutoff)"
        ),
    ),
)


def cleanup_auth_history(
    engine: Engine,
    *,
    confirm: str = "",
    retention_days: int = DEFAULT_RETENTION_DAYS,
    sample_limit: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_confirm(confirm)
    if retention_days < 0:
        raise ValueError("retention_days 不能为负数")

    dry_run = confirm != CONFIRM_TOKEN
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)

    if dry_run:
        with engine.connect() as connection:
            return _cleanup(
                connection,
                dry_run=True,
                cutoff=cutoff,
                retention_days=retention_days,
                sample_limit=sample_limit,
            )

    with engine.begin() as connection:
        return _cleanup(
            connection,
            dry_run=False,
            cutoff=cutoff,
            retention_days=retention_days,
            sample_limit=sample_limit,
        )


def _cleanup(
    connection,
    *,
    dry_run: bool,
    cutoff: datetime,
    retention_days: int,
    sample_limit: int,
) -> dict[str, Any]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    table_columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in tables
    }

    checks: dict[str, dict[str, Any]] = {}
    for spec in AUTH_HISTORY_SPECS:
        checks[spec.key] = _count_or_delete(
            connection,
            tables,
            table_columns,
            spec,
            dry_run=dry_run,
            cutoff=cutoff,
            sample_limit=sample_limit,
        )

    planned = sum(int(item["count"]) for item in checks.values())
    deleted = sum(int(item["deleted"]) for item in checks.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "confirm_token": CONFIRM_TOKEN,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "summary": {
            "planned_delete_count": planned,
            "deleted_count": deleted,
        },
        "checks": checks,
    }


def _count_or_delete(
    connection,
    tables: set[str],
    table_columns: dict[str, set[str]],
    spec: CleanupSpec,
    *,
    dry_run: bool,
    cutoff: datetime,
    sample_limit: int,
) -> dict[str, Any]:
    missing = _missing(spec, tables, table_columns)
    if missing:
        return {
            "status": "skipped",
            "reason": "missing_table_or_column",
            "missing": missing,
            "count": 0,
            "deleted": 0,
            "samples": [],
        }

    params = {"cutoff": cutoff, "sample_limit": sample_limit}
    count = int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {spec.table_name} WHERE {spec.where_sql}"),
            params,
        ).scalar()
        or 0
    )
    samples = [
        {"source_id": str(row["source_id"]), "value": str(row["value"])}
        for row in connection.execute(
            text(
                f"""
                SELECT {spec.id_column} AS source_id,
                       {spec.value_column} AS value
                FROM {spec.table_name}
                WHERE {spec.where_sql}
                ORDER BY {spec.id_column}
                LIMIT :sample_limit
                """
            ),
            params,
        ).mappings().all()
    ]
    deleted = 0
    if not dry_run and count:
        result = connection.execute(
            text(f"DELETE FROM {spec.table_name} WHERE {spec.where_sql}"),
            {"cutoff": cutoff},
        )
        deleted = int(result.rowcount or 0)
    status = "ok"
    if count and dry_run:
        status = "pending_delete"
    elif deleted:
        status = "deleted"
    return {
        "status": status,
        "count": count,
        "deleted": deleted,
        "samples": samples,
    }


def _missing(
    spec: CleanupSpec,
    tables: set[str],
    table_columns: dict[str, set[str]],
) -> list[str]:
    if spec.table_name not in tables:
        return [f"{spec.table_name}.{column}" for column in sorted(spec.required_columns)]
    return [
        f"{spec.table_name}.{column}"
        for column in sorted(set(spec.required_columns) - table_columns.get(spec.table_name, set()))
    ]


def _validate_confirm(confirm: str) -> None:
    if confirm and confirm != CONFIRM_TOKEN:
        raise ValueError(f"--confirm token 不匹配，应为 {CONFIRM_TOKEN}")


def _database_url(explicit_url: str = "") -> str:
    raw_url = explicit_url.strip() or os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        raise SystemExit("DATABASE_URL 未配置，请通过环境变量或 --database-url 传入。")
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run or clean old auth history rows.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL.")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--sample-limit", type=int, default=20, help="Maximum sample rows per check.")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Run destructive cleanup only when this exactly equals {CONFIRM_TOKEN}.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    engine = create_engine(_database_url(args.database_url), future=True)
    try:
        report = cleanup_auth_history(
            engine,
            confirm=args.confirm,
            retention_days=args.retention_days,
            sample_limit=max(0, args.sample_limit),
        )
    finally:
        engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
