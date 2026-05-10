"""Audit database consistency and print a JSON report.

This script is intentionally read-only: it reflects table metadata and runs
SELECT statements only.
"""

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


@dataclass(frozen=True)
class RelationshipCheck:
    key: str
    source_table: str
    source_id_column: str
    local_column: str
    referent_table: str
    referent_column: str
    ignore_blank: bool = True


USER_REFERENCE_CHECKS: tuple[RelationshipCheck, ...] = (
    RelationshipCheck("user_profiles.user_id", "user_profiles", "user_id", "user_id", "users", "id"),
    RelationshipCheck("user_memories.user_id", "user_memories", "user_id", "user_id", "users", "id"),
    RelationshipCheck("auth_refresh_tokens.user_id", "auth_refresh_tokens", "id", "user_id", "users", "id"),
    RelationshipCheck("wechat_mini_identities.user_id", "wechat_mini_identities", "id", "user_id", "users", "id"),
    RelationshipCheck("chat_sessions.user_id", "chat_sessions", "id", "user_id", "users", "id"),
    RelationshipCheck("practice_attempts.user_id", "practice_attempts", "id", "user_id", "users", "id"),
    RelationshipCheck("user_knowledge_stats.user_id", "user_knowledge_stats", "knowledge_point", "user_id", "users", "id"),
    RelationshipCheck("graph_runs.user_id", "graph_runs", "id", "user_id", "users", "id"),
    RelationshipCheck("learning_events.user_id", "learning_events", "id", "user_id", "users", "id"),
    RelationshipCheck("attempts.user_id", "attempts", "id", "user_id", "users", "id"),
    RelationshipCheck("mastery_snapshots.user_id", "mastery_snapshots", "id", "user_id", "users", "id"),
    RelationshipCheck("question_items.user_id", "question_items", "id", "user_id", "users", "id"),
)


GRAPH_RUN_REFERENCE_CHECKS: tuple[RelationshipCheck, ...] = (
    RelationshipCheck("node_runs.graph_run_id", "node_runs", "id", "graph_run_id", "graph_runs", "id"),
    RelationshipCheck("tool_runs.graph_run_id", "tool_runs", "id", "graph_run_id", "graph_runs", "id"),
    RelationshipCheck("learning_events.graph_run_id", "learning_events", "id", "graph_run_id", "graph_runs", "id"),
    RelationshipCheck("attempts.graph_run_id", "attempts", "id", "graph_run_id", "graph_runs", "id"),
    RelationshipCheck("question_items.graph_run_id", "question_items", "id", "graph_run_id", "graph_runs", "id"),
)


CANONICAL_CONCEPT_CHECKS: tuple[RelationshipCheck, ...] = (
    RelationshipCheck("practice_question.concept_id", "practice_question", "question_id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("question_bank_items.concept_id", "question_bank_items", "id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("practice_attempts.concept_id", "practice_attempts", "id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("user_knowledge_stats.concept_id", "user_knowledge_stats", "knowledge_point", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("learning_events.concept_id", "learning_events", "id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("attempts.concept_id", "attempts", "id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("mastery_snapshots.concept_id", "mastery_snapshots", "id", "concept_id", "kb_concept", "concept_id"),
    RelationshipCheck("question_items.primary_concept_id", "question_items", "id", "primary_concept_id", "kb_concept", "concept_id"),
)


TAXONOMY_REFERENCE_CHECKS: tuple[RelationshipCheck, ...] = (
    RelationshipCheck("kb_chapter.subject_id", "kb_chapter", "chapter_id", "subject_id", "kb_subject", "subject_id"),
    RelationshipCheck("kb_topic.subject_id", "kb_topic", "topic_id", "subject_id", "kb_subject", "subject_id"),
    RelationshipCheck("kb_topic.chapter_id", "kb_topic", "topic_id", "chapter_id", "kb_chapter", "chapter_id"),
    RelationshipCheck("kb_concept.subject_id", "kb_concept", "concept_id", "subject_id", "kb_subject", "subject_id"),
    RelationshipCheck("kb_concept.chapter_id", "kb_concept", "concept_id", "chapter_id", "kb_chapter", "chapter_id"),
    RelationshipCheck("kb_concept.topic_id", "kb_concept", "concept_id", "topic_id", "kb_topic", "topic_id"),
    RelationshipCheck("practice_question.subject_id", "practice_question", "question_id", "subject_id", "kb_subject", "subject_id"),
)


ROW_COUNT_TABLES: tuple[str, ...] = (
    "users",
    "user_profiles",
    "user_memories",
    "auth_refresh_tokens",
    "email_verification_challenges",
    "wechat_mini_identities",
    "graph_runs",
    "node_runs",
    "tool_runs",
    "learning_events",
    "attempts",
    "mastery_snapshots",
    "question_items",
    "kb_subject",
    "kb_chapter",
    "kb_topic",
    "kb_concept",
    "practice_question",
)


def audit_data_consistency(engine: Engine, *, sample_limit: int = 20) -> dict[str, Any]:
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        table_columns = {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in tables
        }

        groups = {
            "user_references": USER_REFERENCE_CHECKS,
            "graph_run_references": GRAPH_RUN_REFERENCE_CHECKS,
            "canonical_concept_references": CANONICAL_CONCEPT_CHECKS,
            "taxonomy_references": TAXONOMY_REFERENCE_CHECKS,
        }
        checks: dict[str, dict[str, Any]] = {}
        total_issue_count = 0
        checked_count = 0
        skipped_count = 0

        for group_name, group_checks in groups.items():
            group_report: dict[str, Any] = {}
            for check in group_checks:
                result = _run_relationship_check(connection, tables, table_columns, check, sample_limit)
                group_report[check.key] = result
                if result["status"] == "skipped":
                    skipped_count += 1
                else:
                    checked_count += 1
                    total_issue_count += int(result["count"])
            checks[group_name] = group_report

        row_counts = _row_counts(connection, tables)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {"dialect": engine.dialect.name},
        "summary": {
            "status": "ok" if total_issue_count == 0 else "issues_found",
            "checked_count": checked_count,
            "skipped_count": skipped_count,
            "total_issue_count": total_issue_count,
        },
        "row_counts": row_counts,
        "checks": checks,
    }


def _run_relationship_check(
    connection,
    tables: set[str],
    table_columns: dict[str, set[str]],
    check: RelationshipCheck,
    sample_limit: int,
) -> dict[str, Any]:
    required = {
        check.source_table: {check.source_id_column, check.local_column},
        check.referent_table: {check.referent_column},
    }
    missing = [
        f"{table}.{column}"
        for table, columns in required.items()
        if table not in tables
        for column in columns
    ]
    missing.extend(
        f"{table}.{column}"
        for table, columns in required.items()
        if table in tables
        for column in columns - table_columns.get(table, set())
    )
    if missing:
        return {
            "status": "skipped",
            "reason": "missing_table_or_column",
            "missing": sorted(missing),
            "count": 0,
            "samples": [],
        }

    blank_filter = f"AND child.{check.local_column} <> ''" if check.ignore_blank else ""
    count_sql = text(
        f"""
        SELECT COUNT(*)
        FROM {check.source_table} AS child
        LEFT JOIN {check.referent_table} AS parent
          ON child.{check.local_column} = parent.{check.referent_column}
        WHERE child.{check.local_column} IS NOT NULL
          {blank_filter}
          AND parent.{check.referent_column} IS NULL
        """
    )
    sample_sql = text(
        f"""
        SELECT child.{check.source_id_column} AS source_id,
               child.{check.local_column} AS missing_value
        FROM {check.source_table} AS child
        LEFT JOIN {check.referent_table} AS parent
          ON child.{check.local_column} = parent.{check.referent_column}
        WHERE child.{check.local_column} IS NOT NULL
          {blank_filter}
          AND parent.{check.referent_column} IS NULL
        ORDER BY child.{check.source_id_column}
        LIMIT :sample_limit
        """
    )
    count = int(connection.execute(count_sql).scalar() or 0)
    samples = [
        {"source_id": str(row["source_id"]), "missing_value": str(row["missing_value"])}
        for row in connection.execute(sample_sql, {"sample_limit": sample_limit}).mappings().all()
    ]
    return {
        "status": "ok" if count == 0 else "failed",
        "source_table": check.source_table,
        "local_column": check.local_column,
        "referent_table": check.referent_table,
        "referent_column": check.referent_column,
        "count": count,
        "samples": samples,
    }


def _row_counts(connection, tables: set[str]) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for table_name in ROW_COUNT_TABLES:
        if table_name not in tables:
            counts[table_name] = {"exists": False, "count": 0}
            continue
        counts[table_name] = {
            "exists": True,
            "count": int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0),
        }
    return counts


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
    parser = argparse.ArgumentParser(description="Audit database consistency and print JSON.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Maximum sample rows per failed check.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    engine = create_engine(_database_url(args.database_url), future=True)
    try:
        report = audit_data_consistency(engine, sample_limit=max(0, args.sample_limit))
    finally:
        engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
