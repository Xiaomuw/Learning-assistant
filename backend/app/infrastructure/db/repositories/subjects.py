from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import SubjectModel
from app.infrastructure.db.repositories._shared import serialize_subject_record
from app.shared.schemas.contracts import SubjectRecord
from app.shared.schemas.subject import slugify


def list_subject_records() -> list[SubjectRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(SubjectModel).order_by(SubjectModel.created_at.asc(), SubjectModel.name.asc())
        ).all()
        return [serialize_subject_record(row) for row in rows]


def get_subject_record(subject_id: str) -> SubjectRecord | None:
    with session_scope() as session:
        row = session.get(SubjectModel, subject_id)
        return serialize_subject_record(row) if row else None


def create_subject_record(name: str, icon: str = "📚", description: str = "") -> SubjectRecord:
    subject_id = slugify(name)
    with session_scope() as session:
        duplicate = session.scalar(
            select(SubjectModel).where(or_(SubjectModel.id == subject_id, SubjectModel.name == name))
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
        return serialize_subject_record(subject)


def update_subject_record(
    subject_id: str,
    name: str,
    icon: str = "📚",
    description: str = "",
) -> SubjectRecord | None:
    with session_scope() as session:
        subject = session.get(SubjectModel, subject_id)
        if not subject:
            return None
        duplicate = session.scalar(
            select(SubjectModel).where(SubjectModel.name == name, SubjectModel.id != subject_id)
        )
        if duplicate:
            raise ValueError(f"学科 '{name}' 已存在")
        subject.name = name
        subject.icon = icon or "📚"
        subject.description = description or ""
        session.flush()
        return serialize_subject_record(subject)


def delete_subject_record(subject_id: str) -> SubjectRecord | None:
    with session_scope() as session:
        subject = session.get(SubjectModel, subject_id)
        if not subject:
            return None
        payload = serialize_subject_record(subject)
        session.delete(subject)
        return payload
