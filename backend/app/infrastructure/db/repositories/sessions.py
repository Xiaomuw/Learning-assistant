from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import ChatSessionModel
from app.infrastructure.db.repositories._shared import EMPTY_SESSION_MEMORY, serialize_session_record, utcnow
from app.shared.schemas.contracts import ChatSessionRecord


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _quiz_identity(item: dict[str, Any]) -> str:
    question_id = _compact_text(item.get("question_id"))
    if question_id:
        return f"id:{question_id}"

    options = item.get("options")
    option_text = ""
    if isinstance(options, list):
        option_text = "|".join(
            _compact_text(option.get("text") if isinstance(option, dict) else option)
            for option in options
        )
    question = _compact_text(item.get("question"))
    correct_option = _compact_text(item.get("correct_option"))
    if not question and not option_text:
        return ""
    return f"sig:{question}|{option_text}|{correct_option}"


def _quiz_item_with_context(item: dict[str, Any], fallback_subject_id: str) -> dict[str, Any]:
    payload = dict(item or {})
    subject_id = str(
        payload.get("subject_id")
        or payload.get("notebook_id")
        or fallback_subject_id
        or "general"
    ).strip() or "general"
    payload.setdefault("subject_id", subject_id)
    payload.setdefault("notebook_id", subject_id)
    return payload


def _merge_latest_quiz_items(
    existing_quiz: list[dict[str, Any]] | None,
    incoming_quiz: list[dict[str, Any]] | None,
    *,
    existing_subject_id: str,
    incoming_subject_id: str,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_items(items: list[dict[str, Any]] | None, fallback_subject_id: str) -> None:
        for raw_item in items or []:
            if not isinstance(raw_item, dict):
                continue
            item = _quiz_item_with_context(raw_item, fallback_subject_id)
            identity = _quiz_identity(item)
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            merged.append(item)

    append_items(existing_quiz, existing_subject_id)
    append_items(incoming_quiz, incoming_subject_id)
    return merged


def list_chat_session_records(user_id: str, limit: int = 50) -> list[ChatSessionRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(ChatSessionModel)
            .where(ChatSessionModel.user_id == user_id)
            .order_by(ChatSessionModel.updated_at.desc())
            .limit(limit)
        ).all()
        return [serialize_session_record(row) for row in rows]


def get_chat_session_record(user_id: str, session_id: str) -> ChatSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        return serialize_session_record(row) if row else None


def update_chat_session_memory_record(
    user_id: str,
    session_id: str,
    session_memory: dict[str, Any],
) -> ChatSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        if not row:
            return None
        row.session_memory = {**EMPTY_SESSION_MEMORY, **dict(session_memory or {})}
        row.updated_at = utcnow()
        session.flush()
        return serialize_session_record(row)


def append_chat_turn_record(
    user_id: str,
    session_id: str,
    subject_id: str,
    title: str,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    latest_quiz: list[dict[str, Any]] | None = None,
    session_memory: dict[str, Any] | None = None,
) -> ChatSessionRecord:
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
                session_memory=dict(EMPTY_SESSION_MEMORY),
            )
            session.add(row)
        existing_subject_id = str(row.subject_id or subject_id or "general")
        incoming_subject_id = str(subject_id or existing_subject_id or "general")
        row.user_id = user_id
        row.subject_id = incoming_subject_id
        row.title = (title or row.title or "新对话")[:120]
        messages = list(row.messages or [])
        messages.extend([user_message, assistant_message])
        row.messages = messages
        if latest_quiz:
            row.latest_quiz = _merge_latest_quiz_items(
                row.latest_quiz or [],
                latest_quiz,
                existing_subject_id=existing_subject_id,
                incoming_subject_id=incoming_subject_id,
            )
        if session_memory is not None:
            row.session_memory = {**EMPTY_SESSION_MEMORY, **dict(session_memory)}
        row.updated_at = utcnow()
        session.flush()
        return serialize_session_record(row)


def delete_chat_session_record(user_id: str, session_id: str) -> bool:
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
