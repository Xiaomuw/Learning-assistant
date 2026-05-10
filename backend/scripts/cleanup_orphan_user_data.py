"""Dry-run or clean records whose user or graph-run parent is missing."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

CONFIRM_TOKEN = "CLEANUP_ORPHAN_USER_DATA"


@dataclass(frozen=True)
class UserOrphanSpec:
    table_name: str
    id_column: str
    user_column: str = "user_id"


@dataclass(frozen=True)
class GraphRunChildSpec:
    table_name: str
    id_column: str
    graph_run_column: str = "graph_run_id"


USER_ORPHAN_TABLES: tuple[UserOrphanSpec, ...] = (
    UserOrphanSpec("auth_refresh_tokens", "id"),
    UserOrphanSpec("wechat_mini_identities", "id"),
    UserOrphanSpec("chat_sessions", "id"),
    UserOrphanSpec("practice_attempts", "id"),
    UserOrphanSpec("user_knowledge_stats", "knowledge_point"),
    UserOrphanSpec("learning_events", "id"),
    UserOrphanSpec("attempts", "id"),
    UserOrphanSpec("mastery_snapshots", "id"),
    UserOrphanSpec("question_items", "id"),
    UserOrphanSpec("user_memories", "user_id"),
    UserOrphanSpec("user_profiles", "user_id"),
    UserOrphanSpec("graph_runs", "id"),
)


GRAPH_RUN_CHILD_TABLES: tuple[GraphRunChildSpec, ...] = (
    GraphRunChildSpec("node_runs", "id"),
    GraphRunChildSpec("tool_runs", "id"),
)


def cleanup_orphan_user_data(
    engine: Engine,
    *,
    confirm: str = "",
    sample_limit: int = 20,
) -> dict[str, Any]:
    _validate_confirm(confirm)
    dry_run = confirm != CONFIRM_TOKEN

    if dry_run:
        with engine.connect() as connection:
            return _cleanup(connection, dry_run=True, sample_limit=sample_limit)

    with engine.begin() as connection:
        return _cleanup(connection, dry_run=False, sample_limit=sample_limit)


def _cleanup(connection, *, dry_run: bool, sample_limit: int) -> dict[str, Any]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    table_columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in tables
    }

    graph_run_children: dict[str, dict[str, Any]] = {}
    for spec in GRAPH_RUN_CHILD_TABLES:
        graph_run_children[spec.table_name] = {
            "missing_graph_run": _count_or_delete_missing_graph_run_children(
                connection,
                tables,
                table_columns,
                spec,
                dry_run=dry_run,
                sample_limit=sample_limit,
            ),
            "orphan_user_graph_run": _count_or_delete_orphan_user_graph_run_children(
                connection,
                tables,
                table_columns,
                spec,
                dry_run=dry_run,
                sample_limit=sample_limit,
            ),
        }

    user_orphans: dict[str, dict[str, Any]] = {}
    for spec in USER_ORPHAN_TABLES:
        user_orphans[spec.table_name] = _count_or_delete_user_orphans(
            connection,
            tables,
            table_columns,
            spec,
            dry_run=dry_run,
            sample_limit=sample_limit,
        )

    planned = _sum_key(graph_run_children, "count") + sum(int(item["count"]) for item in user_orphans.values())
    deleted = _sum_key(graph_run_children, "deleted") + sum(int(item["deleted"]) for item in user_orphans.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "confirm_token": CONFIRM_TOKEN,
        "summary": {
            "planned_delete_count": planned,
            "deleted_count": deleted,
        },
        "graph_run_children": graph_run_children,
        "user_orphans": user_orphans,
    }


def _count_or_delete_user_orphans(
    connection,
    tables: set[str],
    table_columns: dict[str, set[str]],
    spec: UserOrphanSpec,
    *,
    dry_run: bool,
    sample_limit: int,
) -> dict[str, Any]:
    required = {spec.table_name: {spec.id_column, spec.user_column}, "users": {"id"}}
    skipped = _missing(required, tables, table_columns)
    if skipped:
        return _skipped(skipped)

    where_sql = (
        f"{spec.user_column} IS NOT NULL "
        f"AND {spec.user_column} <> '' "
        f"AND {spec.user_column} NOT IN (SELECT id FROM users)"
    )
    return _count_or_delete(
        connection,
        spec.table_name,
        spec.id_column,
        spec.user_column,
        where_sql,
        dry_run=dry_run,
        sample_limit=sample_limit,
    )


def _count_or_delete_missing_graph_run_children(
    connection,
    tables: set[str],
    table_columns: dict[str, set[str]],
    spec: GraphRunChildSpec,
    *,
    dry_run: bool,
    sample_limit: int,
) -> dict[str, Any]:
    required = {spec.table_name: {spec.id_column, spec.graph_run_column}, "graph_runs": {"id"}}
    skipped = _missing(required, tables, table_columns)
    if skipped:
        return _skipped(skipped)

    where_sql = (
        f"{spec.graph_run_column} IS NOT NULL "
        f"AND {spec.graph_run_column} <> '' "
        f"AND {spec.graph_run_column} NOT IN (SELECT id FROM graph_runs)"
    )
    return _count_or_delete(
        connection,
        spec.table_name,
        spec.id_column,
        spec.graph_run_column,
        where_sql,
        dry_run=dry_run,
        sample_limit=sample_limit,
    )


def _count_or_delete_orphan_user_graph_run_children(
    connection,
    tables: set[str],
    table_columns: dict[str, set[str]],
    spec: GraphRunChildSpec,
    *,
    dry_run: bool,
    sample_limit: int,
) -> dict[str, Any]:
    required = {
        spec.table_name: {spec.id_column, spec.graph_run_column},
        "graph_runs": {"id", "user_id"},
        "users": {"id"},
    }
    skipped = _missing(required, tables, table_columns)
    if skipped:
        return _skipped(skipped)

    where_sql = (
        f"{spec.graph_run_column} IS NOT NULL "
        f"AND {spec.graph_run_column} <> '' "
        f"AND {spec.graph_run_column} IN ("
        "SELECT graph_runs.id "
        "FROM graph_runs "
        "LEFT JOIN users ON graph_runs.user_id = users.id "
        "WHERE graph_runs.user_id IS NOT NULL "
        "AND graph_runs.user_id <> '' "
        "AND users.id IS NULL"
        ")"
    )
    return _count_or_delete(
        connection,
        spec.table_name,
        spec.id_column,
        spec.graph_run_column,
        where_sql,
        dry_run=dry_run,
        sample_limit=sample_limit,
    )


def _count_or_delete(
    connection,
    table_name: str,
    id_column: str,
    orphan_column: str,
    where_sql: str,
    *,
    dry_run: bool,
    sample_limit: int,
) -> dict[str, Any]:
    count = int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name} WHERE {where_sql}")).scalar() or 0)
    samples = [
        {"source_id": str(row["source_id"]), "orphan_value": str(row["orphan_value"])}
        for row in connection.execute(
            text(
                f"""
                SELECT {id_column} AS source_id,
                       {orphan_column} AS orphan_value
                FROM {table_name}
                WHERE {where_sql}
                ORDER BY {id_column}
                LIMIT :sample_limit
                """
            ),
            {"sample_limit": sample_limit},
        ).mappings().all()
    ]
    deleted = 0
    if not dry_run and count:
        result = connection.execute(text(f"DELETE FROM {table_name} WHERE {where_sql}"))
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
    required: dict[str, set[str]],
    tables: set[str],
    table_columns: dict[str, set[str]],
) -> list[str]:
    missing: list[str] = []
    for table_name, columns in required.items():
        if table_name not in tables:
            missing.extend(f"{table_name}.{column}" for column in sorted(columns))
            continue
        missing.extend(
            f"{table_name}.{column}"
            for column in sorted(columns - table_columns.get(table_name, set()))
        )
    return missing


def _skipped(missing: list[str]) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": "missing_table_or_column",
        "missing": missing,
        "count": 0,
        "deleted": 0,
        "samples": [],
    }


def _sum_key(nested: dict[str, dict[str, dict[str, Any]]], key: str) -> int:
    return sum(
        int(result[key])
        for table_report in nested.values()
        for result in table_report.values()
    )


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
    parser = argparse.ArgumentParser(description="Dry-run or clean orphan user-owned data.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Maximum sample rows per table.")
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
        report = cleanup_orphan_user_data(
            engine,
            confirm=args.confirm,
            sample_limit=max(0, args.sample_limit),
        )
    finally:
        engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
