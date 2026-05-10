from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from sqlalchemy import inspect, text

from app.infrastructure.db.database import Base, engine
from app.knowledge.concept_registry import get_concept_registry
from app.shared.schemas.subject import DEFAULT_SUBJECTS
from app.infrastructure.db.repositories._shared import (
    DEFAULT_APP_SETTINGS,
    ensure_schema_compatibility,
    migrate_legacy_memories,
    migrate_legacy_subjects,
    seed_default_app_settings,
    seed_default_subjects,
)
from app.infrastructure.db.repositories.knowledge_taxonomy import sync_knowledge_taxonomy
from app.infrastructure.db.repositories.users import save_user_memory_record


BOOTSTRAP_APP_DATA_CONFIRM_TOKEN = "BOOTSTRAP_APP_DATA"
BOOTSTRAP_DATA_TABLES = {
    "subjects",
    "app_settings",
    "kb_subject",
    "kb_chapter",
    "kb_topic",
    "kb_concept",
    "user_memories",
}


def bootstrap_app_data(*, confirm: str = "") -> dict[str, object]:
    dry_run = confirm != BOOTSTRAP_APP_DATA_CONFIRM_TOKEN
    report = describe_bootstrap_app_data(dry_run=dry_run)
    if dry_run:
        return report

    _assert_bootstrap_data_tables_ready()
    seed_default_subjects()
    seed_default_app_settings()
    synced_taxonomy = sync_knowledge_taxonomy()
    migrated_subjects = migrate_legacy_subjects()
    migrated_memories = migrate_legacy_memories(save_user_memory_record)

    report.update(
        {
            "synced_taxonomy": synced_taxonomy,
            "migrated_subjects": migrated_subjects,
            "migrated_memories": migrated_memories,
        }
    )
    return report


def describe_bootstrap_app_data(*, dry_run: bool = True) -> dict[str, object]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing_tables = tuple(sorted(BOOTSTRAP_DATA_TABLES - table_names))
    existing_subject_ids = _read_scalar_values("SELECT id FROM subjects") if "subjects" in table_names else ()
    existing_setting_keys = _read_scalar_values("SELECT key FROM app_settings") if "app_settings" in table_names else ()
    db_concept_count = _read_count("kb_concept") if "kb_concept" in table_names else 0
    registry_concept_count = len(get_concept_registry().concepts)
    default_subject_ids = {str(subject["id"]) for subject in DEFAULT_SUBJECTS}
    default_setting_keys = set(DEFAULT_APP_SETTINGS)

    return {
        "dry_run": dry_run,
        "confirm_required": BOOTSTRAP_APP_DATA_CONFIRM_TOKEN if dry_run else "",
        "missing_tables": missing_tables,
        "default_subjects": {
            "configured": len(default_subject_ids),
            "existing": len(default_subject_ids.intersection(existing_subject_ids)),
            "would_insert": len(default_subject_ids - set(existing_subject_ids)),
        },
        "default_app_settings": {
            "configured": len(default_setting_keys),
            "existing": len(default_setting_keys.intersection(existing_setting_keys)),
            "would_insert": len(default_setting_keys - set(existing_setting_keys)),
        },
        "taxonomy": {
            "registry_concept_count": registry_concept_count,
            "db_concept_count": db_concept_count,
            "would_sync": max(0, registry_concept_count - db_concept_count),
        },
        "legacy_subjects": _legacy_subjects_status(),
        "legacy_memories": _legacy_memories_status(),
        "synced_taxonomy": 0,
        "migrated_subjects": 0,
        "migrated_memories": 0,
    }


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    migrated_columns = ensure_schema_compatibility()
    report = bootstrap_app_data(confirm=BOOTSTRAP_APP_DATA_CONFIRM_TOKEN)
    synced_taxonomy = int(report.get("synced_taxonomy") or 0)
    migrated_subjects = int(report.get("migrated_subjects") or 0)
    migrated_memories = int(report.get("migrated_memories") or 0)
    if migrated_columns:
        logger.info(f"✅ 已完成数据库兼容迁移 {migrated_columns} 项")
    if migrated_subjects:
        logger.info(f"✅ 已迁移旧版学科数据 {migrated_subjects} 条")
    if migrated_memories:
        logger.info(f"✅ 已迁移旧版学习记忆 {migrated_memories} 条")
    if synced_taxonomy:
        logger.info(f"✅ 已同步知识点 taxonomy {synced_taxonomy} 条")


def _assert_bootstrap_data_tables_ready() -> None:
    inspector = inspect(engine)
    missing_tables = tuple(sorted(BOOTSTRAP_DATA_TABLES - set(inspector.get_table_names())))
    if missing_tables:
        raise RuntimeError(
            "bootstrap_app_data 需要先完成 Alembic migration，缺少表: "
            + ", ".join(missing_tables)
        )


def _read_scalar_values(statement: str) -> tuple[str, ...]:
    with engine.connect() as connection:
        rows = connection.execute(text(statement)).scalars().all()
    return tuple(str(row) for row in rows if row)


def _read_count(table_name: str) -> int:
    with engine.connect() as connection:
        value = connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    return int(value or 0)


def _legacy_subjects_status() -> dict[str, object]:
    legacy_file = Path("storage/data/subjects.json")
    if not legacy_file.exists():
        return {"file": str(legacy_file), "exists": False, "count": 0}
    try:
        raw = json.loads(legacy_file.read_text(encoding="utf-8"))
    except Exception:
        return {"file": str(legacy_file), "exists": True, "count": 0, "readable": False}
    return {"file": str(legacy_file), "exists": True, "count": len(raw if isinstance(raw, list) else [])}


def _legacy_memories_status() -> dict[str, object]:
    memory_dir = Path("storage/data/memory")
    if not memory_dir.exists():
        return {"directory": str(memory_dir), "exists": False, "count": 0}
    return {
        "directory": str(memory_dir),
        "exists": True,
        "count": len(list(memory_dir.glob("*.json"))),
    }
