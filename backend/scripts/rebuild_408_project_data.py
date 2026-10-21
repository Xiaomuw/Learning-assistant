"""
Rebuild 408 project data.

默认只做 dry-run，且不再内置待核实来源的 408 题库。
仅在隔离的数据库中使用自备、持有相应使用权限的题库。真实清理会删除数据：
  python scripts/rebuild_408_project_data.py --questions-path /secure/authorized.json
  python scripts/rebuild_408_project_data.py --questions-path /secure/authorized.json --confirm CLEAN_408_REBUILD --import-questions
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import inspect, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.db.database import engine, get_sqlalchemy_database_url  # noqa: E402
from app.infrastructure.db.repositories.knowledge_taxonomy import sync_knowledge_taxonomy  # noqa: E402
from app.infrastructure.db.repositories.practice_questions import (  # noqa: E402
    import_practice_questions,
    load_practice_question_json,
    serialize_practice_question,
    validate_practice_questions,
)
from app.knowledge.concept_registry import get_concept_registry  # noqa: E402
from app.services.rag.indexing import index_practice_questions  # noqa: E402
from app.infrastructure.db.models import PracticeQuestionModel  # noqa: E402
from app.infrastructure.db.database import session_scope  # noqa: E402


CONFIRM_TOKEN = "CLEAN_408_REBUILD"
EXPECTED_ALEMBIC_REVISION = "0011_practice_finalizer"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"

STRUCTURED_CLEAR_TABLES = (
    "practice_attempts",
    "user_knowledge_stats",
    "user_memories",
    "question_bank_items",
    "attempts",
    "mastery_snapshots",
    "learning_events",
    "tool_runs",
    "node_runs",
    "graph_runs",
    "question_items",
    "concepts",
    "kb_chunk",
    "practice_question",
)

PRESERVED_TABLES = (
    "users",
    "user_profiles",
    "auth_refresh_tokens",
    "email_verification_challenges",
    "kb_subject",
    "kb_chapter",
    "kb_topic",
    "kb_concept",
    "subjects",
    "app_settings",
)


@dataclass(frozen=True)
class RebuildOptions:
    confirm: str = ""
    questions_path: Path | None = None
    import_questions: bool = False
    index_questions: bool = False
    backup_file: Path | None = None
    strict_index: bool = False

    @property
    def dry_run(self) -> bool:
        return self.confirm != CONFIRM_TOKEN


def rebuild(options: RebuildOptions) -> dict[str, Any]:
    # Fail closed BEFORE any database interaction in destructive mode.
    # No default public question corpus is distributed with this repository.
    if options.import_questions and options.questions_path is None:
        raise ValueError("导入题库必须显式提供 --questions-path")
    if not options.dry_run and (not options.import_questions or options.questions_path is None):
        raise ValueError("真实清理必须同时提供 --import-questions 和 --questions-path")
    report: dict[str, Any] = {
        "dry_run": options.dry_run,
        "expected_revision": EXPECTED_ALEMBIC_REVISION,
        "preserved_tables": list(PRESERVED_TABLES),
    }
    report["alembic"] = _assert_alembic_current()
    report["taxonomy"] = _taxonomy_health()
    report["questions"] = (
        _validate_question_file(options.questions_path)
        if options.questions_path is not None
        else {"skipped": True, "reason": "no_external_questions_path"}
    )

    if options.dry_run:
        report["cleanup"] = _cleanup_project_data(dry_run=True)
        report["backup"] = {"required": False, "created": False}
        report["import"] = {"skipped": True, "reason": "dry_run"}
        report["index"] = {"skipped": True, "reason": "dry_run"}
        return report

    backup_file = _backup_database(options.backup_file)
    report["backup"] = {"required": True, "created": True, "file": str(backup_file)}
    synced = sync_knowledge_taxonomy()
    report["taxonomy"]["synced"] = synced
    report["cleanup"] = _cleanup_project_data(dry_run=False)

    if options.import_questions:
        raw_items = load_practice_question_json(options.questions_path)
        import_result = import_practice_questions(
            raw_items,
            on_conflict="upsert",
            source_file=str(options.questions_path.resolve()),
        )
        report["import"] = import_result.as_dict()
    else:
        report["import"] = {"skipped": True, "reason": "missing --import-questions"}

    if options.index_questions:
        report["index"] = _index_imported_questions(strict=options.strict_index)
    else:
        report["index"] = {"skipped": True, "reason": "missing --index-questions"}
    return report


def _assert_alembic_current() -> dict[str, Any]:
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables:
        raise RuntimeError("未找到 alembic_version，请先运行 alembic upgrade head")
    with engine.begin() as connection:
        revision = str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar() or "")
    if revision != EXPECTED_ALEMBIC_REVISION:
        raise RuntimeError(
            f"Alembic revision 不匹配：current={revision or '<empty>'}, expected={EXPECTED_ALEMBIC_REVISION}"
        )
    return {"current_revision": revision}


def _taxonomy_health() -> dict[str, Any]:
    registry = get_concept_registry()
    registry_ids = set(registry.concepts)
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT concept_id, subject_id FROM kb_concept")).mappings().all()
    db_ids = {str(row["concept_id"]) for row in rows}
    by_subject: dict[str, int] = {}
    for row in rows:
        subject_id = str(row["subject_id"])
        by_subject[subject_id] = by_subject.get(subject_id, 0) + 1
    missing = sorted(registry_ids - db_ids)
    extra = sorted(db_ids - registry_ids)
    if missing:
        raise RuntimeError(f"kb_concept 缺少 Concept Registry 知识点：{missing[:10]}")
    return {
        "registry_concept_count": len(registry_ids),
        "db_concept_count": len(db_ids),
        "missing_in_db": missing,
        "extra_in_db": extra,
        "by_subject": by_subject,
    }


def _validate_question_file(path: Path) -> dict[str, Any]:
    """Validate any permitted question file without the legacy 530-item quota."""
    raw_items = load_practice_question_json(path)
    if not raw_items:
        raise ValueError("不能导入空题库；请提供非空且具有使用权限的题库文件")
    validation = validate_practice_questions(raw_items, source_file=str(path.resolve()))
    validation.raise_for_errors()
    counts: dict[str, int] = {}
    difficulties: dict[str, int] = {"basic": 0, "medium": 0, "hard": 0}
    for item in validation.questions:
        concept_id = str(item["concept_id"])
        counts[concept_id] = counts.get(concept_id, 0) + 1
        difficulty = str(item["difficulty"])
        difficulties[difficulty] = difficulties.get(difficulty, 0) + 1
    return {
        "path": str(path),
        "question_count": len(validation.questions),
        "concept_count": len(counts),
        "per_concept": {"min": min(counts.values()), "max": max(counts.values())},
        "difficulty_distribution": difficulties,
    }


def _cleanup_project_data(*, dry_run: bool) -> dict[str, Any]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    report: dict[str, Any] = {"tables": {}, "pgvector": {}}
    with engine.begin() as connection:
        if {"langchain_pg_collection", "langchain_pg_embedding"}.issubset(tables):
            embedding_count = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM langchain_pg_embedding embeddings
                        JOIN langchain_pg_collection collections
                          ON embeddings.collection_id = collections.uuid
                        WHERE collections.name LIKE 'learning_%'
                        """
                    )
                ).scalar()
                or 0
            )
            collection_count = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM langchain_pg_collection WHERE name LIKE 'learning_%'")
                ).scalar()
                or 0
            )
            report["pgvector"] = {
                "learning_collection_count": collection_count,
                "embedding_count": embedding_count,
            }
            if not dry_run:
                connection.execute(
                    text(
                        """
                        DELETE FROM langchain_pg_embedding
                        WHERE collection_id IN (
                            SELECT uuid FROM langchain_pg_collection WHERE name LIKE 'learning_%'
                        )
                        """
                    )
                )
                connection.execute(text("DELETE FROM langchain_pg_collection WHERE name LIKE 'learning_%'"))
        for table_name in STRUCTURED_CLEAR_TABLES:
            if table_name not in tables:
                report["tables"][table_name] = {"exists": False, "rows": 0}
                continue
            count = int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
            report["tables"][table_name] = {"exists": True, "rows": count}
            if not dry_run and count:
                connection.execute(text(f"DELETE FROM {table_name}"))
    return report


def _backup_database(backup_file: Path | None) -> Path:
    pg_dump = shutil.which("pg_dump")
    backup_path = backup_file or _default_backup_file()
    if not pg_dump:
        return _write_jsonl_backup(backup_path.with_suffix(".jsonl"))
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = get_sqlalchemy_database_url().replace("postgresql+psycopg://", "postgresql://", 1)
    result = subprocess.run(
        [pg_dump, "--format=custom", "--file", str(backup_path), database_url],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump 备份失败：{result.stderr or result.stdout}")
    return backup_path


def _write_jsonl_backup(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "metadata",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "format": "jsonl",
                    "reason": "pg_dump_not_found",
                    "tables": list(STRUCTURED_CLEAR_TABLES),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        with engine.begin() as connection:
            for table_name in STRUCTURED_CLEAR_TABLES:
                if table_name not in tables:
                    continue
                rows = connection.execute(text(f"SELECT * FROM {table_name}")).mappings()
                for row in rows:
                    handle.write(
                        json.dumps(
                            {"type": "table_row", "table": table_name, "row": _jsonable(dict(row))},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            if {"langchain_pg_collection", "langchain_pg_embedding"}.issubset(tables):
                collection_rows = connection.execute(
                    text("SELECT * FROM langchain_pg_collection WHERE name LIKE 'learning_%'")
                ).mappings()
                for row in collection_rows:
                    handle.write(
                        json.dumps(
                            {"type": "table_row", "table": "langchain_pg_collection", "row": _jsonable(dict(row))},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                embedding_rows = connection.execute(
                    text(
                        """
                        SELECT embeddings.id,
                               embeddings.collection_id,
                               embeddings.custom_id,
                               embeddings.document,
                               embeddings.cmetadata,
                               embeddings.embedding::text AS embedding
                        FROM langchain_pg_embedding embeddings
                        JOIN langchain_pg_collection collections
                          ON embeddings.collection_id = collections.uuid
                        WHERE collections.name LIKE 'learning_%'
                        """
                    )
                ).mappings()
                for row in embedding_rows:
                    handle.write(
                        json.dumps(
                            {"type": "table_row", "table": "langchain_pg_embedding", "row": _jsonable(dict(row))},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
    return path


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _default_backup_file() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_BACKUP_DIR / f"learning_assistant_before_408_rebuild_{timestamp}.dump"


def _index_imported_questions(*, strict: bool) -> dict[str, Any]:
    with session_scope() as session:
        rows = session.query(PracticeQuestionModel).all()
        items = [serialize_practice_question(row) for row in rows]
    try:
        written = index_practice_questions(items)
    except Exception as exc:
        if strict:
            raise
        return {
            "skipped": True,
            "reason": "index_failed",
            "error_type": exc.__class__.__name__,
            "question_count": len(items),
        }
    return {"skipped": False, "question_count": len(items), "written_chunks": written}


def main() -> None:
    parser = argparse.ArgumentParser(description="清理并重建 408 项目学习数据")
    parser.add_argument("--confirm", default="", help=f"真实清理必须传入 {CONFIRM_TOKEN}")
    parser.add_argument("--questions-path", type=Path, default=None, help="显式指定有权使用的本地题库；不再提供默认题库")
    parser.add_argument("--backup-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="兼容显式 dry-run；不传 confirm 时也默认 dry-run")
    parser.add_argument("--import-questions", action="store_true")
    parser.add_argument("--index-questions", action="store_true")
    parser.add_argument("--strict-index", action="store_true", help="题库向量索引失败时让脚本失败")
    args = parser.parse_args()

    report = rebuild(
        RebuildOptions(
            confirm="" if args.dry_run else args.confirm,
            questions_path=args.questions_path,
            import_questions=args.import_questions,
            index_questions=args.index_questions,
            backup_file=args.backup_file,
            strict_index=args.strict_index,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
