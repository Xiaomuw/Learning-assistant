from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.infrastructure.db.models import ChatAsyncJobModel
from app.infrastructure.db.repositories._shared import session_scope, to_iso8601, utcnow


def serialize_chat_async_job(row: ChatAsyncJobModel | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "job_id": row.job_id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "request_id": row.request_id,
        "status": row.status,
        "result_json": dict(row.result_json or {}) if row.result_json else None,
        "error_json": dict(row.error_json or {}) if row.error_json else None,
        "created_at": to_iso8601(row.created_at),
        "updated_at": to_iso8601(row.updated_at),
    }


def create_chat_async_job(
    *,
    job_id: str,
    user_id: str,
    session_id: str,
    request_id: str,
) -> dict[str, Any]:
    now = utcnow()
    with session_scope() as session:
        row = session.get(ChatAsyncJobModel, job_id)
        if row is None:
            row = ChatAsyncJobModel(
                job_id=job_id,
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
                status="pending",
                result_json=None,
                error_json=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
        return serialize_chat_async_job(row) or {}


def get_chat_async_job(*, user_id: str, job_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalars(
            select(ChatAsyncJobModel).where(
                ChatAsyncJobModel.job_id == job_id,
                ChatAsyncJobModel.user_id == user_id,
            )
        ).first()
        return serialize_chat_async_job(row)


def mark_chat_async_job_completed(*, job_id: str, result: dict[str, Any]) -> None:
    now = utcnow()
    with session_scope() as session:
        row = session.get(ChatAsyncJobModel, job_id)
        if row is None:
            return
        row.status = "completed"
        row.result_json = dict(result)
        row.error_json = None
        row.updated_at = now
        session.add(row)


def mark_chat_async_job_failed(*, job_id: str, error: dict[str, Any]) -> None:
    now = utcnow()
    with session_scope() as session:
        row = session.get(ChatAsyncJobModel, job_id)
        if row is None:
            return
        row.status = "failed"
        row.error_json = dict(error)
        row.updated_at = now
        session.add(row)
