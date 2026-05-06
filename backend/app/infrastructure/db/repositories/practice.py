from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import PracticeAttemptModel, QuestionBankItemModel
from app.infrastructure.db.repositories._shared import (
    QUIZ_DIFFICULTY_ORDER,
    normalize_option_rationales,
    normalize_quiz_options,
    serialize_practice_attempt_record,
    serialize_question_bank_item_record,
    utcnow,
)
from app.shared.schemas.contracts import PracticeAttemptRecord, QuestionBankItemRecord, UserMemoryRecord


def upsert_question_bank_item_records(items: list[dict[str, Any]]) -> int:
    saved = 0
    with session_scope() as session:
        for item in items:
            question_id = str(item.get("id") or item.get("question_id") or uuid.uuid4())
            row = session.get(QuestionBankItemModel, question_id)
            if row is None:
                row = QuestionBankItemModel(id=question_id)
                session.add(row)
            row.subject_id = str(item.get("subject_id") or "general")
            row.knowledge_point = str(item.get("knowledge_point") or "").strip()
            row.stem = str(item.get("question") or item.get("stem") or "").strip()
            row.options_json = normalize_quiz_options(item.get("options"))
            row.correct_option = str(item.get("correct_option") or "A").strip().upper()[:1]
            row.explanation = str(item.get("explanation") or "").strip()
            row.option_rationales_json = normalize_option_rationales(item.get("option_rationales"))
            row.source_name = str(item.get("source_name") or "").strip()
            row.source_year = item.get("source_year")
            row.difficulty = str(item.get("difficulty") or "基础").strip() or "基础"
            row.tags_json = [
                str(tag).strip()
                for tag in list(item.get("tags", []) or [])
                if str(tag).strip()
            ]
            row.updated_at = utcnow()
            saved += 1
        session.flush()
    return saved


def list_question_bank_item_records(
    *,
    subject_id: str | None = None,
    knowledge_points: list[str] | None = None,
    difficulty: str | None = None,
    years: list[int] | None = None,
    limit: int = 20,
) -> list[QuestionBankItemRecord]:
    with session_scope() as session:
        stmt = select(QuestionBankItemModel)
        if subject_id:
            stmt = stmt.where(QuestionBankItemModel.subject_id == subject_id)
        normalized_points = [str(point).strip() for point in list(knowledge_points or []) if str(point).strip()]
        if normalized_points:
            stmt = stmt.where(QuestionBankItemModel.knowledge_point.in_(normalized_points))
        if difficulty:
            stmt = stmt.where(QuestionBankItemModel.difficulty == difficulty)
        normalized_years = [int(year) for year in list(years or [])]
        if normalized_years:
            stmt = stmt.where(QuestionBankItemModel.source_year.in_(normalized_years))
        stmt = stmt.order_by(
            QuestionBankItemModel.source_year.desc(),
            QuestionBankItemModel.updated_at.desc(),
        ).limit(limit)
        rows = session.scalars(stmt).all()
        return [serialize_question_bank_item_record(row) for row in rows]


def list_practice_recommendation_records(
    memory: UserMemoryRecord,
    *,
    subject_id: str | None = None,
    limit: int = 6,
) -> list[QuestionBankItemRecord]:
    focus_points = [*memory.weak_points, *memory.recent_topics]
    focus_points = list(dict.fromkeys(point for point in focus_points if point))
    bank_items = list_question_bank_item_records(
        subject_id=subject_id,
        knowledge_points=focus_points[:5] or None,
        limit=max(limit * 2, limit),
    )
    scored: list[tuple[int, QuestionBankItemRecord]] = []
    weak_point_set = set(memory.weak_points)
    recent_topic_set = set(memory.recent_topics)
    for item in bank_items:
        point = item.knowledge_point
        score = 0
        if point in weak_point_set:
            score += 3
        if point in recent_topic_set:
            score += 2
        score += max(0, 3 - QUIZ_DIFFICULTY_ORDER.get(str(item.difficulty), 0))
        if item.source_year:
            score += 1
        scored.append((score, item))
    scored.sort(
        key=lambda pair: (pair[0], int(pair[1].source_year or 0), pair[1].question),
        reverse=True,
    )
    return [item for _, item in scored[:limit]]


def create_practice_attempt_record(
    *,
    user_id: str,
    session_id: str = "",
    subject_id: str = "general",
    question_id: str = "",
    question_snapshot: dict[str, Any] | None = None,
    selected_option: str,
    is_correct: bool,
    knowledge_point: str,
    source_type: str,
) -> PracticeAttemptRecord:
    with session_scope() as session:
        attempt = PracticeAttemptModel(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            subject_id=subject_id,
            question_id=question_id,
            question_snapshot=dict(question_snapshot or {}),
            selected_option=selected_option.strip().upper()[:1],
            is_correct=bool(is_correct),
            knowledge_point=knowledge_point,
            source_type=source_type or "ai_generated",
        )
        session.add(attempt)
        session.flush()
        return serialize_practice_attempt_record(attempt)
