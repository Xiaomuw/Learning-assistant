from __future__ import annotations

from datetime import datetime
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
        "conversation_id": row.conversation_id,
        "client_request_id": row.client_request_id,
        "request_id": row.request_id,
        "trace_id": row.trace_id,
        "status": row.status,
        "request_payload": dict(row.request_payload or {}) if row.request_payload else None,
        "final_answer": row.final_answer,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "route": row.route,
        "result_json": dict(row.result_json or {}) if row.result_json else None,
        "error_json": dict(row.error_json or {}) if row.error_json else None,
        "expires_at": to_iso8601(row.expires_at),
        "created_at": to_iso8601(row.created_at),
        "updated_at": to_iso8601(row.updated_at),
    }


def create_chat_async_job(
    *,
    job_id: str,
    user_id: str,
    session_id: str,
    request_id: str,
    conversation_id: str | None = None,
    client_request_id: str | None = None,
    request_payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    now = utcnow()
    with session_scope() as session:
        row = session.get(ChatAsyncJobModel, job_id)
        if row is None:
            row = ChatAsyncJobModel(
                job_id=job_id,
                user_id=user_id,
                session_id=session_id,
                conversation_id=conversation_id or session_id,
                client_request_id=client_request_id or None,
                request_id=request_id,
                trace_id=trace_id or request_id,
                status="pending",
                request_payload=dict(request_payload or {}),
                final_answer="",
                error_code="",
                error_message="",
                route="",
                result_json=None,
                error_json=None,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
        else:
            changed = False
            if not row.conversation_id:
                row.conversation_id = conversation_id or session_id
                changed = True
            if client_request_id and not row.client_request_id:
                row.client_request_id = client_request_id
                changed = True
            if trace_id and not row.trace_id:
                row.trace_id = trace_id
                changed = True
            if request_payload and not row.request_payload:
                row.request_payload = dict(request_payload)
                changed = True
            if expires_at and not row.expires_at:
                row.expires_at = expires_at
                changed = True
            if changed:
                row.updated_at = now
                session.add(row)
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
        row.final_answer = str(result.get("final_answer") or "")
        row.error_code = ""
        row.error_message = ""
        row.route = str(result.get("route") or row.route or "")
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
        row.error_code = str(error.get("code") or error.get("reason") or "chat_job_failed")
        row.error_message = str(error.get("error") or error.get("message") or "")
        row.updated_at = now
        session.add(row)
