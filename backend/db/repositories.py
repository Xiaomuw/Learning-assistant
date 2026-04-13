"""
数据库读写仓储
==============
统一封装 Subjects / Memory / Sessions 的持久化逻辑。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import inspect, or_, select, text

from db.database import Base, engine, session_scope
from db.models import (
    AppSettingModel,
    ChatSessionModel,
    SubjectModel,
    UserMemoryModel,
    UserProfileModel,
)
from schemas.subject import DEFAULT_SUBJECTS, slugify


EMPTY_MEMORY = {
    "weak_points": [],
    "error_count": {},
    "recent_topics": [],
    "last_session": "",
}

EMPTY_USER_PROFILE = {
    "user_id": "",
    "display_name": "",
    "agent_style_name": "",
    "agent_style_prompt": "",
    "onboarding_completed": False,
}

DEFAULT_APP_SETTINGS = {
    "chat_model": os.getenv("DEFAULT_CHAT_MODEL", "openai-gpt-oss-20b"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso8601(value: Any) -> str:
    if not value:
        return ""

    if isinstance(value, str):
        return value

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_display_name(user_id: str) -> str:
    if user_id == "default_user":
        return "学习者_7492"

    checksum = sum(ord(ch) for ch in user_id) % 10000
    return f"学习者_{checksum:04d}"


def _serialize_subject(subject: SubjectModel) -> dict[str, Any]:
    return {
        "id": subject.id,
        "name": subject.name,
        "icon": subject.icon,
        "description": subject.description,
        "doc_count": 0,
        "created_at": _to_iso8601(subject.created_at),
    }


def _serialize_memory(memory: UserMemoryModel | None) -> dict[str, Any]:
    if not memory:
        return dict(EMPTY_MEMORY)

    return {
        "weak_points": list(memory.weak_points or []),
        "error_count": dict(memory.error_count or {}),
        "recent_topics": list(memory.recent_topics or []),
        "last_session": memory.last_session or "",
    }


def _serialize_user_profile(profile: UserProfileModel | None, user_id: str) -> dict[str, Any]:
    if not profile:
        return {
            **EMPTY_USER_PROFILE,
            "user_id": user_id,
            "display_name": _default_display_name(user_id),
        }

    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name or _default_display_name(user_id),
        "agent_style_name": profile.agent_style_name or "",
        "agent_style_prompt": profile.agent_style_prompt or "",
        "onboarding_completed": bool(profile.onboarding_completed),
    }


def _serialize_session(session: ChatSessionModel) -> dict[str, Any]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "subject_id": session.subject_id,
        "title": session.title,
        "messages": list(session.messages or []),
        "latest_quiz": list(session.latest_quiz or []),
        "created_at": _to_iso8601(session.created_at),
        "updated_at": _to_iso8601(session.updated_at),
    }


def _upsert_subject_if_missing(
    subject_id: str,
    name: str,
    icon: str,
    description: str,
    created_at: str | None = None,
) -> None:
    with session_scope() as session:
        existing = session.get(SubjectModel, subject_id)
        if existing:
            return

        name_conflict = session.scalar(
            select(SubjectModel).where(SubjectModel.name == name)
        )
        if name_conflict:
            return

        subject = SubjectModel(
            id=subject_id,
            name=name,
            icon=icon or "📚",
            description=description or "",
        )
        if created_at:
            try:
                subject.created_at = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        session.add(subject)


def seed_default_subjects() -> None:
    for subject in DEFAULT_SUBJECTS:
        _upsert_subject_if_missing(
            subject_id=subject["id"],
            name=subject["name"],
            icon=subject["icon"],
            description=subject["description"],
        )


def seed_default_app_settings() -> None:
    for key, value in DEFAULT_APP_SETTINGS.items():
        with session_scope() as session:
            existing = session.get(AppSettingModel, key)
            if existing:
                continue

            session.add(AppSettingModel(key=key, value=value))


def migrate_legacy_subjects() -> None:
    legacy_file = Path("data/subjects.json")
    if not legacy_file.exists():
        return

    try:
        subjects = json.loads(legacy_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"⚠️ 读取旧版 subjects.json 失败: {exc}")
        return

    migrated = 0
    for subject in subjects:
        subject_id = subject.get("id") or slugify(subject.get("name", "未命名学科"))
        before = get_subject_by_id(subject_id)
        _upsert_subject_if_missing(
            subject_id=subject_id,
            name=subject.get("name", "未命名学科"),
            icon=subject.get("icon", "📚"),
            description=subject.get("description", ""),
            created_at=subject.get("created_at"),
        )
        after = get_subject_by_id(subject_id)
        if not before and after:
            migrated += 1

    if migrated:
        logger.info(f"✅ 已迁移旧版学科数据 {migrated} 条")


def migrate_legacy_memories() -> None:
    memory_dir = Path("data/memory")
    if not memory_dir.exists():
        return

    migrated = 0
    for path in memory_dir.glob("*.json"):
        user_id = path.stem

        with session_scope() as session:
            existing = session.get(UserMemoryModel, user_id)
            if existing:
                continue

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"⚠️ 读取旧版记忆文件失败 {path.name}: {exc}")
            continue

        save_user_memory(user_id, {
            "weak_points": raw.get("weak_points", []),
            "error_count": raw.get("error_count", {}),
            "recent_topics": raw.get("recent_topics", []),
            "last_session": raw.get("last_session", ""),
        })
        migrated += 1

    if migrated:
        logger.info(f"✅ 已迁移旧版学习记忆 {migrated} 条")


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_schema_compatibility()
    seed_default_subjects()
    seed_default_app_settings()
    migrate_legacy_subjects()
    migrate_legacy_memories()


def _ensure_schema_compatibility() -> None:
    inspector = inspect(engine)
    if "user_profiles" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("user_profiles")}
    alter_statements: list[str] = []

    if "display_name" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE user_profiles ADD COLUMN display_name VARCHAR(120) NOT NULL DEFAULT ''"
        )

    if not alter_statements:
        return

    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))

    logger.info(f"✅ 已完成 user_profiles 表兼容迁移，共 {len(alter_statements)} 项")


def list_subjects() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(
            select(SubjectModel).order_by(SubjectModel.created_at.asc(), SubjectModel.name.asc())
        ).all()
        return [_serialize_subject(row) for row in rows]


def get_subject_by_id(subject_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        subject = session.get(SubjectModel, subject_id)
        return _serialize_subject(subject) if subject else None


def create_subject(name: str, icon: str = "📚", description: str = "") -> dict[str, Any]:
    subject_id = slugify(name)

    with session_scope() as session:
        duplicate = session.scalar(
            select(SubjectModel).where(
                or_(SubjectModel.id == subject_id, SubjectModel.name == name)
            )
        )
        if duplicate:
            raise ValueError(f"学科 '{name}' 已存在")

        subject = SubjectModel(
            id=subject_id,
            name=name,
            icon=icon or "📚",
            description=description or "",
        )
        session.add(subject)
        session.flush()
        return _serialize_subject(subject)


def update_subject(
    subject_id: str,
    name: str,
    icon: str = "📚",
    description: str = "",
) -> dict[str, Any] | None:
    with session_scope() as session:
        subject = session.get(SubjectModel, subject_id)
        if not subject:
            return None

        duplicate = session.scalar(
            select(SubjectModel).where(
                SubjectModel.name == name,
                SubjectModel.id != subject_id,
            )
        )
        if duplicate:
            raise ValueError(f"学科 '{name}' 已存在")

        subject.name = name
        subject.icon = icon or "📚"
        subject.description = description or ""
        session.flush()
        return _serialize_subject(subject)


def delete_subject(subject_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        subject = session.get(SubjectModel, subject_id)
        if not subject:
            return None

        payload = _serialize_subject(subject)
        session.delete(subject)
        return payload


def get_user_memory(user_id: str) -> dict[str, Any]:
    with session_scope() as session:
        memory = session.get(UserMemoryModel, user_id)
        return _serialize_memory(memory)


def get_user_profile(user_id: str) -> dict[str, Any]:
    with session_scope() as session:
        profile = session.get(UserProfileModel, user_id)
        return _serialize_user_profile(profile, user_id)


def save_user_memory(user_id: str, memory: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(UserMemoryModel, user_id)
        if row is None:
            row = UserMemoryModel(user_id=user_id)
            session.add(row)

        row.weak_points = list(memory.get("weak_points", []))
        row.error_count = dict(memory.get("error_count", {}))
        row.recent_topics = list(memory.get("recent_topics", []))
        row.last_session = memory.get("last_session", "")
        row.updated_at = _utcnow()

        session.flush()
        return _serialize_memory(row)


def save_user_profile(user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(UserProfileModel, user_id)
        if row is None:
            row = UserProfileModel(user_id=user_id)
            session.add(row)

        row.display_name = str(
            profile.get("display_name") or row.display_name or _default_display_name(user_id)
        )[:120]
        row.agent_style_name = str(profile.get("agent_style_name", "") or "")[:120]
        row.agent_style_prompt = str(profile.get("agent_style_prompt", "") or "")[:4000]
        row.onboarding_completed = bool(profile.get("onboarding_completed", False))
        row.updated_at = _utcnow()

        session.flush()
        return _serialize_user_profile(row, user_id)


def list_chat_sessions(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(
            select(ChatSessionModel)
            .where(ChatSessionModel.user_id == user_id)
            .order_by(ChatSessionModel.updated_at.desc())
            .limit(limit)
        ).all()
        return [_serialize_session(row) for row in rows]


def append_chat_turn(
    user_id: str,
    session_id: str,
    subject_id: str,
    title: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    latest_quiz: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(ChatSessionModel, session_id)
        if row is None:
            row = ChatSessionModel(
                id=session_id,
                user_id=user_id,
                subject_id=subject_id,
                title=title or "新对话",
                messages=[],
                latest_quiz=[],
            )
            session.add(row)

        row.user_id = user_id
        row.subject_id = subject_id or row.subject_id or "general"
        row.title = (title or row.title or "新对话")[:120]

        messages = list(row.messages or [])
        messages.extend([user_message, assistant_message])
        row.messages = messages
        if latest_quiz:
            row.latest_quiz = latest_quiz
        row.updated_at = _utcnow()

        session.flush()
        return _serialize_session(row)


def delete_chat_session(user_id: str, session_id: str) -> bool:
    with session_scope() as session:
        row = session.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        if not row:
            return False

        session.delete(row)
        return True


def get_latest_quiz(user_id: str) -> list[dict[str, Any]]:
    sessions = list_chat_sessions(user_id=user_id, limit=20)
    for session in sessions:
        latest_quiz = session.get("latest_quiz") or []
        if latest_quiz:
            return latest_quiz
    return []


def get_app_setting(key: str, default: str | None = None) -> str | None:
    with session_scope() as session:
        row = session.get(AppSettingModel, key)
        if not row:
            return default
        return row.value


def set_app_setting(key: str, value: str) -> str:
    with session_scope() as session:
        row = session.get(AppSettingModel, key)
        if row is None:
            row = AppSettingModel(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = _utcnow()

        session.flush()
        return row.value
