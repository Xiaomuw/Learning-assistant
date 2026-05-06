from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text

from app.infrastructure.db.database import engine, session_scope
from app.infrastructure.db.models import (
    AppSettingModel,
    AuthRefreshTokenModel,
    ChatSessionModel,
    EmailVerificationChallengeModel,
    PracticeAttemptModel,
    QuestionBankItemModel,
    SubjectModel,
    UserKnowledgeStatModel,
    UserMemoryModel,
    UserModel,
    UserProfileModel,
)
from app.shared.schemas.contracts import (
    AppSettingRecord,
    AuthUserRecord,
    ChatSessionRecord,
    EmailVerificationChallengeRecord,
    KnowledgeMasteryRecord,
    PracticeAttemptRecord,
    QuestionBankItemRecord,
    RefreshTokenRecord,
    SubjectRecord,
    UserMemoryRecord,
    UserProfileRecord,
)
from app.shared.schemas.subject import DEFAULT_SUBJECTS, slugify


EMPTY_MEMORY = {
    "weak_points": [],
    "error_count": {},
    "recent_topics": [],
    "last_session": "",
}

EMPTY_SESSION_MEMORY = {
    "summary_text": "",
    "active_topic": "",
    "current_goal": "",
    "open_loops": [],
    "resolved_points": [],
    "last_question_type": "",
    "last_updated_at": "",
}

DEFAULT_APP_SETTINGS = {
    "chat_model": os.getenv("DEFAULT_CHAT_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "openai-gpt-4.1",
}

QUIZ_DIFFICULTY_ORDER = {
    "基础": 0,
    "变式": 1,
    "易错": 2,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso8601(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_utc_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def default_display_name(user_id: str) -> str:
    if user_id == "default_user":
        return "学习者_7492"
    checksum = sum(ord(ch) for ch in user_id) % 10000
    return f"学习者_{checksum:04d}"


def normalize_quiz_options(options: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for option in list(options or []):
        key = str(option.get("key", "") or "").strip().upper()
        text = str(option.get("text", "") or "").strip()
        if key in {"A", "B", "C", "D"} and text:
            normalized.append({"key": key, "text": text})
    return normalized[:4]


def normalize_option_rationales(raw: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in ("A", "B", "C", "D"):
        value = str((raw or {}).get(key, "") or "").strip()
        if value:
            normalized[key] = value
    return normalized


def serialize_subject_record(subject: SubjectModel) -> SubjectRecord:
    return SubjectRecord(
        id=subject.id,
        name=subject.name,
        icon=subject.icon,
        description=subject.description,
        doc_count=0,
        created_at=to_iso8601(subject.created_at),
    )


def serialize_memory_record(memory: UserMemoryModel | None) -> UserMemoryRecord:
    if not memory:
        return UserMemoryRecord()
    return UserMemoryRecord(
        weak_points=list(memory.weak_points or []),
        error_count=dict(memory.error_count or {}),
        recent_topics=list(memory.recent_topics or []),
        last_session=memory.last_session or "",
    )


def serialize_knowledge_stat_record(row: UserKnowledgeStatModel) -> KnowledgeMasteryRecord:
    return KnowledgeMasteryRecord(
        user_id=row.user_id,
        subject_id=row.subject_id,
        knowledge_point=row.knowledge_point,
        exposure_count=int(row.exposure_count or 0),
        attempt_count=int(row.attempt_count or 0),
        correct_count=int(row.correct_count or 0),
        wrong_count=int(row.wrong_count or 0),
        mastery_score=round(float(row.mastery_score or 0.0), 2),
        mastery_level=row.mastery_level or "weak",
        last_seen_at=to_iso8601(row.last_seen_at),
        last_practiced_at=to_iso8601(row.last_practiced_at),
        updated_at=to_iso8601(row.updated_at),
    )


def serialize_user_profile_record(profile: UserProfileModel | None, user_id: str) -> UserProfileRecord:
    if not profile:
        return UserProfileRecord(
            user_id=user_id,
            display_name=default_display_name(user_id),
        )
    return UserProfileRecord(
        user_id=profile.user_id,
        display_name=profile.display_name or default_display_name(user_id),
        agent_style_name=profile.agent_style_name or "",
        agent_style_prompt=profile.agent_style_prompt or "",
        onboarding_completed=bool(profile.onboarding_completed),
    )


def serialize_user_record(
    user: UserModel | None,
    profile: UserProfileModel | None = None,
) -> AuthUserRecord | None:
    if not user:
        return None
    display_name = default_display_name(user.id)
    if profile:
        display_name = profile.display_name or display_name
    return AuthUserRecord(
        id=user.id,
        email=user.email,
        display_name=display_name,
        status=user.status,
        last_login_at=to_iso8601(user.last_login_at),
    )


def serialize_refresh_token_record(row: AuthRefreshTokenModel | None) -> RefreshTokenRecord | None:
    if not row:
        return None
    return RefreshTokenRecord(
        id=row.id,
        user_id=row.user_id,
        token_jti=row.token_jti,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


def serialize_email_verification_challenge_record(
    row: EmailVerificationChallengeModel | None,
) -> EmailVerificationChallengeRecord | None:
    if not row:
        return None
    return EmailVerificationChallengeRecord(
        id=row.id,
        email=row.email,
        purpose=row.purpose,
        code_hash=row.code_hash,
        expires_at=row.expires_at,
        attempt_count=int(row.attempt_count or 0),
        max_attempts=int(row.max_attempts or 5),
        verified_at=row.verified_at,
        consumed_at=row.consumed_at,
        last_sent_at=row.last_sent_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def normalize_session_memory(session_memory: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(EMPTY_SESSION_MEMORY)
    raw = dict(session_memory or {})
    for key in payload:
        value = raw.get(key)
        if key in {"open_loops", "resolved_points"}:
            payload[key] = list(value or [])
        else:
            payload[key] = value or ""
    return payload


def serialize_session_record(session: ChatSessionModel) -> ChatSessionRecord:
    return ChatSessionRecord(
        id=session.id,
        user_id=session.user_id,
        subject_id=session.subject_id,
        title=session.title,
        messages=list(session.messages or []),
        latest_quiz=list(session.latest_quiz or []),
        session_memory=normalize_session_memory(session.session_memory),
        created_at=to_iso8601(session.created_at),
        updated_at=to_iso8601(session.updated_at),
    )


def serialize_question_bank_item_record(item: QuestionBankItemModel) -> QuestionBankItemRecord:
    return QuestionBankItemRecord(
        id=item.id,
        question_id=item.id,
        subject_id=item.subject_id,
        knowledge_point=item.knowledge_point,
        question=item.stem,
        options=normalize_quiz_options(item.options_json),
        correct_option=item.correct_option,
        explanation=item.explanation,
        option_rationales=normalize_option_rationales(item.option_rationales_json),
        difficulty=item.difficulty,
        source_type="question_bank",
        source_name=item.source_name,
        source_year=item.source_year,
        hint="",
        tags=list(item.tags_json or []),
    )


def serialize_practice_attempt_record(attempt: PracticeAttemptModel) -> PracticeAttemptRecord:
    return PracticeAttemptRecord(
        id=attempt.id,
        user_id=attempt.user_id,
        session_id=attempt.session_id,
        subject_id=attempt.subject_id,
        question_id=attempt.question_id,
        question_snapshot=dict(attempt.question_snapshot or {}),
        selected_option=attempt.selected_option,
        is_correct=bool(attempt.is_correct),
        knowledge_point=attempt.knowledge_point,
        source_type=attempt.source_type,
        created_at=to_iso8601(attempt.created_at),
    )


def serialize_app_setting_record(row: AppSettingModel | None, key: str, default: str | None = None) -> AppSettingRecord:
    return AppSettingRecord(key=key, value=row.value if row else (default or ""))


def upsert_subject_if_missing(
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
        name_conflict = session.scalar(select(SubjectModel).where(SubjectModel.name == name))
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
                subject.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                pass
        session.add(subject)


def seed_default_subjects() -> None:
    for subject in DEFAULT_SUBJECTS:
        upsert_subject_if_missing(
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


def migrate_legacy_subjects() -> int:
    legacy_file = Path("storage/data/subjects.json")
    if not legacy_file.exists():
        return 0
    try:
        subjects = json.loads(legacy_file.read_text(encoding="utf-8"))
    except Exception:
        return 0
    migrated = 0
    for subject in subjects:
        subject_id = subject.get("id") or slugify(subject.get("name", "未命名学科"))
        upsert_subject_if_missing(
            subject_id=subject_id,
            name=subject.get("name", "未命名学科"),
            icon=subject.get("icon", "📚"),
            description=subject.get("description", ""),
            created_at=subject.get("created_at"),
        )
        migrated += 1
    return migrated


def migrate_legacy_memories(save_memory_fn) -> int:
    memory_dir = Path("storage/data/memory")
    if not memory_dir.exists():
        return 0
    migrated = 0
    for path in memory_dir.glob("*.json"):
        user_id = path.stem
        with session_scope() as session:
            existing = session.get(UserMemoryModel, user_id)
            if existing:
                continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        save_memory_fn(
            user_id,
            UserMemoryRecord(
                weak_points=raw.get("weak_points", []),
                error_count=raw.get("error_count", {}),
                recent_topics=raw.get("recent_topics", []),
                last_session=raw.get("last_session", ""),
            ),
        )
        migrated += 1
    return migrated


def ensure_schema_compatibility() -> int:
    inspector = inspect(engine)
    if "user_profiles" not in inspector.get_table_names():
        return 0
    alter_statements: list[str] = []
    existing_columns = {column["name"] for column in inspector.get_columns("user_profiles")}
    if "display_name" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE user_profiles ADD COLUMN display_name VARCHAR(120) NOT NULL DEFAULT ''"
        )
    if "session_memory" not in {column["name"] for column in inspector.get_columns("chat_sessions")}:
        alter_statements.append("ALTER TABLE chat_sessions ADD COLUMN session_memory JSONB")
    if not alter_statements:
        return 0
    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))
    return len(alter_statements)
