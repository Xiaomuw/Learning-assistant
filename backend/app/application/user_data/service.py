from __future__ import annotations

from app.application.errors import NotFoundError
from app.domains.mastery.service import get_mastery
from app.infrastructure.db.repositories.sessions import delete_chat_session_record, list_chat_session_records
from app.infrastructure.db.repositories.users import (
    get_user_memory_record,
    get_user_profile_record,
    save_user_profile_record,
)
from app.shared.schemas.contracts import (
    ChatSessionRecord,
    DeleteResult,
    KnowledgeMasteryResult,
    LatestQuizBundle,
    UserMemoryRecord,
    UserProfileRecord,
)
from app.shared.schemas.subject import normalize_subject_id


def get_memory(user_id: str) -> UserMemoryRecord:
    return get_user_memory_record(user_id)


def get_knowledge_mastery(
    user_id: str,
    *,
    subject_id: str | None = None,
    limit: int = 50,
) -> KnowledgeMasteryResult:
    return get_mastery(user_id=user_id, subject_id=subject_id, limit=limit)


def get_profile(user_id: str) -> UserProfileRecord:
    return get_user_profile_record(user_id)


def update_profile(user_id: str, updates: dict) -> UserProfileRecord:
    existing = get_user_profile_record(user_id)
    next_profile = UserProfileRecord(
        user_id=user_id,
        display_name=existing.display_name if updates.get("display_name") is None else updates["display_name"],
        agent_style_name=(
            existing.agent_style_name if updates.get("agent_style_name") is None else updates["agent_style_name"]
        ),
        agent_style_prompt=(
            existing.agent_style_prompt if updates.get("agent_style_prompt") is None else updates["agent_style_prompt"]
        ),
        onboarding_completed=(
            existing.onboarding_completed
            if updates.get("onboarding_completed") is None
            else updates["onboarding_completed"]
        ),
    )
    return save_user_profile_record(user_id, next_profile)


def get_sessions(user_id: str) -> list[ChatSessionRecord]:
    return list_chat_session_records(user_id=user_id)


def remove_session(user_id: str, session_id: str) -> DeleteResult:
    deleted = delete_chat_session_record(user_id=user_id, session_id=session_id)
    if not deleted:
        raise NotFoundError("聊天记录不存在")
    return DeleteResult(message="聊天记录已删除")


def get_latest_quiz_bundle(user_id: str) -> LatestQuizBundle:
    sessions = get_sessions(user_id)
    for session in sessions:
        latest_quiz = session.latest_quiz or []
        if latest_quiz:
            return LatestQuizBundle(
                session_id=session.id,
                subject_id=normalize_subject_id(session.subject_id),
                quiz_items=latest_quiz,
            )
    return LatestQuizBundle()
