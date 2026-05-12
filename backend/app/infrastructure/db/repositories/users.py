from __future__ import annotations

from typing import Any

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import UserMemoryModel, UserProfileModel
from app.infrastructure.db.repositories._shared import (
    default_display_name,
    serialize_memory_record,
    serialize_user_profile_record,
    utcnow,
)
from app.shared.schemas.contracts import UserMemoryRecord, UserProfileRecord

MAX_FINALIZED_PRACTICE_ATTEMPT_IDS = 1000


def get_user_memory_record(user_id: str) -> UserMemoryRecord:
    with session_scope() as session:
        memory = session.get(UserMemoryModel, user_id)
        return serialize_memory_record(memory)


def get_user_profile_record(user_id: str) -> UserProfileRecord:
    with session_scope() as session:
        profile = session.get(UserProfileModel, user_id)
        return serialize_user_profile_record(profile, user_id)


def save_user_memory_record(user_id: str, memory: UserMemoryRecord) -> UserMemoryRecord:
    with session_scope() as session:
        row = session.get(UserMemoryModel, user_id)
        if row is None:
            row = UserMemoryModel(user_id=user_id)
            session.add(row)
        row.weak_points = list(memory.weak_points)
        row.error_count = dict(memory.error_count)
        row.recent_topics = list(memory.recent_topics)
        row.last_session = memory.last_session
        row.updated_at = utcnow()
        session.flush()
        return serialize_memory_record(row)


def apply_practice_attempt_memory_finalization(
    user_id: str,
    *,
    legacy_attempt_id: str,
    weak_points: list[str],
    error_count: dict[str, Any],
    recent_topics: list[str],
    last_session: str,
) -> tuple[UserMemoryRecord, bool]:
    normalized_attempt_id = str(legacy_attempt_id or "").strip()
    with session_scope() as session:
        row = session.get(UserMemoryModel, user_id)
        if row is None:
            row = UserMemoryModel(user_id=user_id)
            session.add(row)
            session.flush()
        if session.get_bind().dialect.name == "postgresql":
            session.refresh(row, with_for_update=True)

        finalized_ids = [str(item) for item in list(row.finalized_practice_attempt_ids or []) if str(item)]
        if normalized_attempt_id and normalized_attempt_id in finalized_ids:
            return serialize_memory_record(row), False

        row.weak_points = list(weak_points)
        row.error_count = dict(error_count)
        row.recent_topics = list(recent_topics)
        row.last_session = str(last_session or "")
        if normalized_attempt_id:
            row.finalized_practice_attempt_ids = [
                normalized_attempt_id,
                *[item for item in finalized_ids if item != normalized_attempt_id],
            ][:MAX_FINALIZED_PRACTICE_ATTEMPT_IDS]
        row.updated_at = utcnow()
        session.flush()
        return serialize_memory_record(row), True


def save_user_profile_record(user_id: str, profile: UserProfileRecord) -> UserProfileRecord:
    with session_scope() as session:
        row = session.get(UserProfileModel, user_id)
        if row is None:
            row = UserProfileModel(user_id=user_id)
            session.add(row)
        row.display_name = str(profile.display_name or row.display_name or default_display_name(user_id))[:120]
        row.agent_style_name = str(profile.agent_style_name or "")[:120]
        row.agent_style_prompt = str(profile.agent_style_prompt or "")[:4000]
        row.onboarding_completed = bool(profile.onboarding_completed)
        row.updated_at = utcnow()
        session.flush()
        return serialize_user_profile_record(row, user_id)
