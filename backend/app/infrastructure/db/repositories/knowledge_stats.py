from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import UserKnowledgeStatModel
from app.infrastructure.db.repositories._shared import serialize_knowledge_stat_record, utcnow
from app.shared.schemas.contracts import KnowledgeMasteryRecord


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _compute_mastery_score(
    *,
    exposure_count: int,
    attempt_count: int,
    correct_count: int,
    wrong_count: int,
) -> float:
    correct_rate = correct_count / attempt_count if attempt_count > 0 else 0.0
    exposure_bonus = min(exposure_count, 5) / 5
    wrong_penalty = min(wrong_count, 5) / 5
    score = correct_rate * 70 + exposure_bonus * 20 - wrong_penalty * 10
    return round(_clamp_score(score), 2)


def _mastery_level(score: float) -> str:
    if score >= 80:
        return "mastered"
    if score >= 50:
        return "learning"
    return "weak"


def _normalize_subject_id(subject_id: str | None) -> str:
    return str(subject_id or "general").strip() or "general"


def _normalize_point(knowledge_point: str | None) -> str:
    return str(knowledge_point or "").strip()


def _recalculate(row: UserKnowledgeStatModel) -> None:
    row.mastery_score = _compute_mastery_score(
        exposure_count=int(row.exposure_count or 0),
        attempt_count=int(row.attempt_count or 0),
        correct_count=int(row.correct_count or 0),
        wrong_count=int(row.wrong_count or 0),
    )
    row.mastery_level = _mastery_level(float(row.mastery_score or 0.0))
    row.updated_at = utcnow()


def _get_or_create_stat_in_session(
    session,
    *,
    user_id: str,
    subject_id: str,
    knowledge_point: str,
) -> UserKnowledgeStatModel:
    row = session.get(
        UserKnowledgeStatModel,
        {
            "user_id": user_id,
            "subject_id": subject_id,
            "knowledge_point": knowledge_point,
        },
    )
    if row is None:
        row = UserKnowledgeStatModel(
            user_id=user_id,
            subject_id=subject_id,
            knowledge_point=knowledge_point,
        )
        session.add(row)
    return row


def record_knowledge_exposure(
    *,
    user_id: str,
    subject_id: str | None,
    knowledge_point: str | None,
    count: int = 1,
) -> KnowledgeMasteryRecord | None:
    point = _normalize_point(knowledge_point)
    if not user_id or not point:
        return None
    normalized_subject_id = _normalize_subject_id(subject_id)
    now = utcnow()
    with session_scope() as session:
        row = _get_or_create_stat_in_session(
            session,
            user_id=user_id,
            subject_id=normalized_subject_id,
            knowledge_point=point,
        )
        row.exposure_count = int(row.exposure_count or 0) + max(1, int(count or 1))
        row.last_seen_at = now
        _recalculate(row)
        session.flush()
        return serialize_knowledge_stat_record(row)


def record_knowledge_attempt(
    *,
    user_id: str,
    subject_id: str | None,
    knowledge_point: str | None,
    is_correct: bool,
) -> KnowledgeMasteryRecord | None:
    point = _normalize_point(knowledge_point)
    if not user_id or not point:
        return None
    normalized_subject_id = _normalize_subject_id(subject_id)
    now = utcnow()
    with session_scope() as session:
        row = _get_or_create_stat_in_session(
            session,
            user_id=user_id,
            subject_id=normalized_subject_id,
            knowledge_point=point,
        )
        row.attempt_count = int(row.attempt_count or 0) + 1
        if is_correct:
            row.correct_count = int(row.correct_count or 0) + 1
        else:
            row.wrong_count = int(row.wrong_count or 0) + 1
        row.last_practiced_at = now
        row.last_seen_at = row.last_seen_at or now
        _recalculate(row)
        session.flush()
        return serialize_knowledge_stat_record(row)


def list_knowledge_mastery_records(
    *,
    user_id: str,
    subject_id: str | None = None,
    limit: int = 50,
) -> list[KnowledgeMasteryRecord]:
    with session_scope() as session:
        stmt = select(UserKnowledgeStatModel).where(UserKnowledgeStatModel.user_id == user_id)
        if subject_id:
            stmt = stmt.where(UserKnowledgeStatModel.subject_id == subject_id)
        stmt = stmt.order_by(
            UserKnowledgeStatModel.mastery_score.asc(),
            UserKnowledgeStatModel.updated_at.desc(),
        ).limit(max(1, min(int(limit or 50), 100)))
        rows = session.scalars(stmt).all()
        return [serialize_knowledge_stat_record(row) for row in rows]
