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
    chapter_id: str | None = None,
    topic_id: str | None = None,
    concept_id: str | None = None,
    concept_name: str | None = None,
) -> KnowledgeMasteryRecord | None:
    return record_knowledge_exposure(
        user_id=user_id,
        subject_id=subject_id,
        knowledge_point=knowledge_point,
        chapter_id=chapter_id,
        topic_id=topic_id,
        concept_id=concept_id,
        concept_name=concept_name,
    )


def record_attempt(
    *,
    user_id: str,
    subject_id: str | None,
    knowledge_point: str | None,
    chapter_id: str | None = None,
    topic_id: str | None = None,
    concept_id: str | None = None,
    concept_name: str | None = None,
    is_correct: bool = False,
) -> KnowledgeMasteryRecord | None:
    return record_knowledge_attempt(
        user_id=user_id,
        subject_id=subject_id,
        knowledge_point=knowledge_point,
        chapter_id=chapter_id,
        topic_id=topic_id,
        concept_id=concept_id,
        concept_name=concept_name,
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
