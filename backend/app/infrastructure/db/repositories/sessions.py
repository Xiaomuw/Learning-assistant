from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import ChatSessionModel
from app.infrastructure.db.repositories._shared import EMPTY_SESSION_MEMORY, serialize_session_record, utcnow
from app.shared.schemas.contracts import ChatSessionRecord


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
        row.user_id = user_id
        row.subject_id = subject_id or row.subject_id or "general"
        row.title = (title or row.title or "新对话")[:120]
        messages = list(row.messages or [])
        messages.extend([user_message, assistant_message])
        row.messages = messages
        if latest_quiz:
            row.latest_quiz = latest_quiz
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
