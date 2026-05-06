from __future__ import annotations

from loguru import logger

from app.infrastructure.db.database import Base, engine
from app.infrastructure.db.repositories._shared import (
    ensure_schema_compatibility,
    migrate_legacy_memories,
    migrate_legacy_subjects,
    seed_default_app_settings,
    seed_default_subjects,
)
from app.infrastructure.db.repositories.users import save_user_memory_record


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    migrated_columns = ensure_schema_compatibility()
    seed_default_subjects()
    seed_default_app_settings()
    migrated_subjects = migrate_legacy_subjects()
    migrated_memories = migrate_legacy_memories(save_user_memory_record)
    if migrated_columns:
        logger.info(f"✅ 已完成数据库兼容迁移 {migrated_columns} 项")
    if migrated_subjects:
        logger.info(f"✅ 已迁移旧版学科数据 {migrated_subjects} 条")
    if migrated_memories:
        logger.info(f"✅ 已迁移旧版学习记忆 {migrated_memories} 条")
