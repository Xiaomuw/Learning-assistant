from __future__ import annotations

import uuid
from datetime import timezone, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    PracticeAttemptFinalizationJobModel,
    PracticeAttemptModel,
    PracticeQuestionModel,
    QuestionBankItemModel,
)
from app.infrastructure.db.repositories._shared import (
    QUIZ_DIFFICULTY_ORDER,
    normalize_option_rationales,
    normalize_quiz_options,
    serialize_practice_attempt_record,
    serialize_question_bank_item_record,
    utcnow,
)
from app.shared.schemas.contracts import PracticeAttemptRecord, QuestionBankItemRecord, UserMemoryRecord
from app.knowledge.concept_registry import ConceptMatch, get_concept_registry
from app.infrastructure.db.repositories.practice_questions import normalize_difficulty

FINALIZATION_JOB_MAX_ATTEMPTS = 5
FINALIZATION_JOB_STALE_TIMEOUT = timedelta(minutes=15)
FINALIZATION_JOB_MAX_BACKOFF = timedelta(hours=1)


def upsert_question_bank_item_records(items: list[dict[str, Any]]) -> int:
    saved = 0
    with session_scope() as session:
        for item in items:
            question_id = str(item.get("id") or item.get("question_id") or uuid.uuid4())
            concept_payload = _concept_payload_for_item(item)
            row = session.get(QuestionBankItemModel, question_id)
            if row is None:
                row = QuestionBankItemModel(id=question_id)
                session.add(row)
            row.subject_id = str(item.get("subject_id") or "general")
            row.knowledge_point = str(item.get("knowledge_point") or "").strip()
            row.chapter_id = str(concept_payload.get("chapter_id") or item.get("chapter_id") or "")
            row.topic_id = str(concept_payload.get("topic_id") or item.get("topic_id") or "")
            row.concept_id = str(concept_payload.get("concept_id") or item.get("concept_id") or "")
            row.concept_name = str(concept_payload.get("concept_name") or item.get("concept_name") or "")
            row.concept_mapping_status = str(concept_payload.get("concept_mapping_status") or item.get("concept_mapping_status") or "")
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
    practice_items = list_practice_question_records(
        subject_id=subject_id,
        knowledge_points=knowledge_points,
        difficulty=difficulty,
        limit=limit,
    )
    if len(practice_items) >= limit:
        return practice_items[:limit]
    remaining = max(0, limit - len(practice_items))
    legacy_items = _list_legacy_question_bank_item_records(
        subject_id=subject_id,
        knowledge_points=knowledge_points,
        difficulty=difficulty,
        years=years,
        limit=remaining,
    )
    seen = {item.question_id for item in practice_items}
    merged = list(practice_items)
    for item in legacy_items:
        if item.question_id in seen:
            continue
        merged.append(item)
        seen.add(item.question_id)
        if len(merged) >= limit:
            break
    return merged


def list_practice_question_records(
    *,
    subject_id: str | None = None,
    knowledge_points: list[str] | None = None,
    difficulty: str | None = None,
    limit: int = 20,
) -> list[QuestionBankItemRecord]:
    with session_scope() as session:
        stmt = select(PracticeQuestionModel)
        if subject_id:
            stmt = stmt.where(PracticeQuestionModel.subject_id == subject_id)
        normalized_points = [str(point).strip() for point in list(knowledge_points or []) if str(point).strip()]
        if normalized_points:
            stmt = stmt.where(
                or_(
                    PracticeQuestionModel.concept_id.in_(normalized_points),
                    PracticeQuestionModel.concept_name.in_(normalized_points),
                )
            )
        normalized_difficulty = normalize_difficulty(difficulty) if difficulty else ""
        if normalized_difficulty:
            stmt = stmt.where(PracticeQuestionModel.difficulty == normalized_difficulty)
        stmt = stmt.order_by(
            PracticeQuestionModel.updated_at.desc(),
            PracticeQuestionModel.question_id.asc(),
        ).limit(max(1, int(limit or 20)))
        rows = session.scalars(stmt).all()
        return [_practice_question_record(row) for row in rows]


def _list_legacy_question_bank_item_records(
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
            stmt = stmt.where(
                or_(
                    QuestionBankItemModel.knowledge_point.in_(normalized_points),
                    QuestionBankItemModel.concept_id.in_(normalized_points),
                    QuestionBankItemModel.concept_name.in_(normalized_points),
                )
            )
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


def _practice_question_record(row: PracticeQuestionModel) -> QuestionBankItemRecord:
    options_json = dict(row.options_json or {})
    return QuestionBankItemRecord(
        id=row.question_id,
        question_id=row.question_id,
        subject_id=row.subject_id,
        knowledge_point=row.concept_name or row.concept_id,
        chapter_id=str((row.metadata_json or {}).get("canonical", {}).get("chapter_id") or ""),
        topic_id=str((row.metadata_json or {}).get("canonical", {}).get("topic_id") or ""),
        concept_id=row.concept_id,
        concept_name=row.concept_name,
        concept_mapping_status="matched",
        question=row.stem,
        options=[{"key": key, "text": str(options_json.get(key) or "")} for key in ("A", "B", "C", "D")],
        correct_option=row.answer,
        explanation=row.explanation,
        option_rationales={},
        difficulty=row.difficulty,
        source_type="question_bank",
        source_name="practice_question",
        source_year=None,
        hint=row.common_trap,
        tags=["408", "practice_question"],
    )


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
    chapter_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    concept_name: str = "",
    concept_mapping_status: str = "",
    source_type: str = "ai_generated",
    idempotency_key: str = "",
) -> PracticeAttemptRecord:
    with session_scope() as session:
        normalized_key = str(idempotency_key or "").strip()
        if normalized_key:
            existing = session.scalars(
                select(PracticeAttemptModel)
                .where(PracticeAttemptModel.idempotency_key == normalized_key)
                .limit(1)
            ).first()
            if existing is not None:
                return serialize_practice_attempt_record(existing)
        attempt = _new_practice_attempt_model(
            user_id=user_id,
            session_id=session_id,
            subject_id=subject_id,
            question_id=question_id,
            question_snapshot=question_snapshot,
            selected_option=selected_option,
            is_correct=is_correct,
            knowledge_point=knowledge_point,
            chapter_id=chapter_id,
            topic_id=topic_id,
            concept_id=concept_id,
            concept_name=concept_name,
            concept_mapping_status=concept_mapping_status,
            source_type=source_type,
            idempotency_key=normalized_key,
        )
        session.add(attempt)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            if not normalized_key:
                raise
            existing = session.scalars(
                select(PracticeAttemptModel)
                .where(PracticeAttemptModel.idempotency_key == normalized_key)
                .limit(1)
            ).first()
            if existing is None:
                raise
            return serialize_practice_attempt_record(existing)
        return serialize_practice_attempt_record(attempt)


def create_practice_attempt_record_with_finalization_job(
    *,
    user_id: str,
    session_id: str = "",
    subject_id: str = "general",
    question_id: str = "",
    question_snapshot: dict[str, Any] | None = None,
    selected_option: str,
    is_correct: bool,
    knowledge_point: str,
    chapter_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    concept_name: str = "",
    concept_mapping_status: str = "",
    source_type: str = "ai_generated",
    idempotency_key: str = "",
) -> tuple[PracticeAttemptRecord, dict[str, Any]]:
    with session_scope() as session:
        normalized_key = str(idempotency_key or "").strip()
        attempt = None
        if normalized_key:
            attempt = session.scalars(
                select(PracticeAttemptModel)
                .where(PracticeAttemptModel.idempotency_key == normalized_key)
                .limit(1)
            ).first()
        if attempt is None:
            attempt = _new_practice_attempt_model(
                user_id=user_id,
                session_id=session_id,
                subject_id=subject_id,
                question_id=question_id,
                question_snapshot=question_snapshot,
                selected_option=selected_option,
                is_correct=is_correct,
                knowledge_point=knowledge_point,
                chapter_id=chapter_id,
                topic_id=topic_id,
                concept_id=concept_id,
                concept_name=concept_name,
                concept_mapping_status=concept_mapping_status,
                source_type=source_type,
                idempotency_key=normalized_key,
            )
            session.add(attempt)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                if not normalized_key:
                    raise
                attempt = session.scalars(
                    select(PracticeAttemptModel)
                    .where(PracticeAttemptModel.idempotency_key == normalized_key)
                    .limit(1)
                ).first()
                if attempt is None:
                    raise

        job = session.scalars(
            select(PracticeAttemptFinalizationJobModel)
            .where(PracticeAttemptFinalizationJobModel.legacy_attempt_id == attempt.id)
            .limit(1)
        ).first()
        if job is None:
            job = PracticeAttemptFinalizationJobModel(
                id=str(uuid.uuid4()),
                legacy_attempt_id=attempt.id,
                status="pending",
                next_run_at=utcnow(),
            )
            session.add(job)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                job = session.scalars(
                    select(PracticeAttemptFinalizationJobModel)
                    .where(PracticeAttemptFinalizationJobModel.legacy_attempt_id == attempt.id)
                    .limit(1)
                ).first()
                if job is None:
                    raise
        return serialize_practice_attempt_record(attempt), _serialize_finalization_job(job)


def find_practice_attempt_record_for_question(
    *,
    user_id: str,
    session_id: str = "",
    subject_id: str = "general",
    question_id: str = "",
) -> PracticeAttemptRecord | None:
    normalized_question_id = str(question_id or "").strip()
    if not normalized_question_id:
        return None

    with session_scope() as session:
        row = session.scalars(
            select(PracticeAttemptModel)
            .where(
                PracticeAttemptModel.user_id == user_id,
                PracticeAttemptModel.session_id == session_id,
                PracticeAttemptModel.subject_id == subject_id,
                PracticeAttemptModel.question_id == normalized_question_id,
            )
            .order_by(PracticeAttemptModel.created_at.desc())
            .limit(1)
        ).first()
        return serialize_practice_attempt_record(row) if row is not None else None


def get_practice_attempt_record_by_id(attempt_id: str) -> PracticeAttemptRecord | None:
    with session_scope() as session:
        row = session.get(PracticeAttemptModel, str(attempt_id or "").strip())
        return serialize_practice_attempt_record(row) if row is not None else None


def get_practice_attempt_finalization_job(job_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.get(PracticeAttemptFinalizationJobModel, str(job_id or "").strip())
        return _serialize_finalization_job(row) if row is not None else None


def claim_practice_attempt_finalization_job(job_id: str) -> dict[str, Any] | None:
    normalized_id = str(job_id or "").strip()
    if not normalized_id:
        return None
    with session_scope() as session:
        stmt = select(PracticeAttemptFinalizationJobModel).where(
            PracticeAttemptFinalizationJobModel.id == normalized_id
        )
        if session.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update()
        row = session.scalars(stmt).first()
        if row is None:
            return None
        now = utcnow()
        status = str(row.status or "")
        if status in {"completed", "dead"}:
            return None
        if status in {"pending", "failed"} and not _job_is_due(row, now=now):
            return None
        if status == "running":
            locked_at = _as_aware_utc(row.locked_at)
            if locked_at is None or locked_at > now - FINALIZATION_JOB_STALE_TIMEOUT:
                return None
        elif status not in {"pending", "failed"}:
            return None
        row.status = "running"
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.locked_at = now
        row.updated_at = now
        session.flush()
        return _serialize_finalization_job(row)


def complete_practice_attempt_finalization_job(job_id: str) -> None:
    _update_practice_attempt_finalization_job(
        job_id,
        status="completed",
        last_error="",
        clear_lock=True,
    )


def fail_practice_attempt_finalization_job(job_id: str, error: str) -> str:
    with session_scope() as session:
        row = session.get(PracticeAttemptFinalizationJobModel, str(job_id or "").strip())
        if row is None or row.status in {"completed", "dead"}:
            return "skipped"
        now = utcnow()
        attempt_count = int(row.attempt_count or 0)
        row.status = "dead" if attempt_count >= FINALIZATION_JOB_MAX_ATTEMPTS else "failed"
        row.last_error = str(error or "")[:1000]
        row.locked_at = None
        row.next_run_at = None if row.status == "dead" else now + _finalization_job_backoff(attempt_count)
        row.updated_at = now
        session.flush()
        return str(row.status or "failed")


def list_due_practice_attempt_finalization_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    now = utcnow()
    stale_before = now - FINALIZATION_JOB_STALE_TIMEOUT
    with session_scope() as session:
        rows = session.scalars(
            select(PracticeAttemptFinalizationJobModel)
            .where(
                or_(
                    (
                        PracticeAttemptFinalizationJobModel.status.in_(["pending", "failed"])
                        & or_(
                            PracticeAttemptFinalizationJobModel.next_run_at.is_(None),
                            PracticeAttemptFinalizationJobModel.next_run_at <= now,
                        )
                    ),
                    (
                        (PracticeAttemptFinalizationJobModel.status == "running")
                        & PracticeAttemptFinalizationJobModel.locked_at.is_not(None)
                        & (PracticeAttemptFinalizationJobModel.locked_at <= stale_before)
                    ),
                ),
            )
            .order_by(PracticeAttemptFinalizationJobModel.created_at.asc())
            .limit(max(1, min(int(limit or 20), 100)))
        ).all()
        return [_serialize_finalization_job(row) for row in rows]


def _new_practice_attempt_model(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    question_id: str,
    question_snapshot: dict[str, Any] | None,
    selected_option: str,
    is_correct: bool,
    knowledge_point: str,
    chapter_id: str,
    topic_id: str,
    concept_id: str,
    concept_name: str,
    concept_mapping_status: str,
    source_type: str,
    idempotency_key: str = "",
) -> PracticeAttemptModel:
    return PracticeAttemptModel(
        id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        question_id=question_id,
        question_snapshot=dict(question_snapshot or {}),
        selected_option=selected_option.strip().upper()[:1],
        is_correct=bool(is_correct),
        knowledge_point=knowledge_point,
        chapter_id=chapter_id,
        topic_id=topic_id,
        concept_id=concept_id,
        concept_name=concept_name,
        concept_mapping_status=concept_mapping_status,
        source_type=source_type or "ai_generated",
        idempotency_key=idempotency_key,
    )


def _serialize_finalization_job(row: PracticeAttemptFinalizationJobModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.id,
        "legacy_attempt_id": row.legacy_attempt_id,
        "status": row.status,
        "attempt_count": int(row.attempt_count or 0),
        "locked_at": row.locked_at.isoformat() if row.locked_at else "",
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else "",
        "last_error": row.last_error or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _update_practice_attempt_finalization_job(
    job_id: str,
    *,
    status: str,
    last_error: str,
    clear_lock: bool,
) -> None:
    with session_scope() as session:
        row = session.get(PracticeAttemptFinalizationJobModel, str(job_id or "").strip())
        if row is None:
            return
        row.status = status
        row.last_error = last_error
        row.updated_at = utcnow()
        if clear_lock:
            row.locked_at = None
        if status == "completed":
            row.next_run_at = None


def _job_is_due(row: PracticeAttemptFinalizationJobModel, *, now) -> bool:
    next_run_at = _as_aware_utc(row.next_run_at)
    return next_run_at is None or next_run_at <= now


def _finalization_job_backoff(attempt_count: int) -> timedelta:
    exponent = max(0, int(attempt_count or 1) - 1)
    seconds = min(int(FINALIZATION_JOB_MAX_BACKOFF.total_seconds()), 60 * (2 ** exponent))
    return timedelta(seconds=seconds)


def _as_aware_utc(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _concept_payload_for_item(item: dict[str, Any]) -> dict[str, str]:
    subject_id = str(item.get("subject_id") or "general").strip()
    explicit_concept_id = str(item.get("concept_id") or item.get("primary_concept_id") or "").strip()
    registry = get_concept_registry()
    if explicit_concept_id:
        concept = registry.get_concept(explicit_concept_id)
        if concept is not None:
            return {
                **concept.metadata(),
                "concept_mapping_status": "matched",
            }

    query = "\n".join(
        str(item.get(key) or "")
        for key in ("knowledge_point", "concept_name", "question", "stem", "explanation")
        if str(item.get(key) or "").strip()
    )
    match = registry.match_query(query, subject_id=subject_id)
    return _concept_payload_from_match(match)


def _concept_payload_from_match(match: ConceptMatch) -> dict[str, str]:
    if match.status != "matched":
        return {
            "chapter_id": "",
            "topic_id": "",
            "concept_id": "",
            "concept_name": "",
            "concept_mapping_status": match.status,
        }
    concept = get_concept_registry().get_concept(match.concept_id)
    if concept is None:
        return {
            "chapter_id": match.chapter_id or "",
            "topic_id": match.topic_id or "",
            "concept_id": match.concept_id or "",
            "concept_name": match.concept_name or "",
            "concept_mapping_status": match.status,
        }
    return {
        "chapter_id": concept.chapter_id,
        "topic_id": concept.topic_id,
        "concept_id": concept.concept_id,
        "concept_name": concept.concept_name,
        "concept_mapping_status": "matched",
    }
