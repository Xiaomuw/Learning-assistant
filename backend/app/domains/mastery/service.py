from __future__ import annotations

from app.infrastructure.db.repositories.knowledge_stats import (
    list_knowledge_mastery_records,
    record_knowledge_attempt,
    record_knowledge_exposure,
)
from app.shared.schemas.contracts import KnowledgeMasteryRecord, KnowledgeMasteryResult


def record_exposure(
    *,
    user_id: str,
    subject_id: str | None,
    knowledge_point: str | None,
) -> KnowledgeMasteryRecord | None:
    return record_knowledge_exposure(
        user_id=user_id,
        subject_id=subject_id,
        knowledge_point=knowledge_point,
    )


def record_attempt(
    *,
    user_id: str,
    subject_id: str | None,
    knowledge_point: str | None,
    is_correct: bool,
) -> KnowledgeMasteryRecord | None:
    return record_knowledge_attempt(
        user_id=user_id,
        subject_id=subject_id,
        knowledge_point=knowledge_point,
        is_correct=is_correct,
    )


def get_mastery(
    *,
    user_id: str,
    subject_id: str | None = None,
    limit: int = 50,
) -> KnowledgeMasteryResult:
    return KnowledgeMasteryResult(
        user_id=user_id,
        subject_id=subject_id,
        items=list_knowledge_mastery_records(
            user_id=user_id,
            subject_id=subject_id,
            limit=limit,
        ),
    )
