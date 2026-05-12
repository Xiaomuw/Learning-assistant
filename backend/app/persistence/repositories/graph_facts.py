from __future__ import annotations

import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    GraphConceptModel,
    GraphAttemptModel,
    GraphQuestionItemModel,
    GraphRunModel,
    LearningEventModel,
    MasterySnapshotModel,
    NodeRunModel,
    ToolRunModel,
)
from app.knowledge.concept_registry import get_concept_registry
from app.persistence.interfaces import (
    AttemptRepository,
    ConceptRepository,
    GraphRunRepository,
    LearningEventRepository,
    MasterySnapshotRepository,
    QuestionItemRepository,
    ToolRunRepository,
)
from app.shared.schemas.agent_graphs import LearningEvent, ToolResult, learning_event_hash_key


SessionFactory = Callable[[], AbstractContextManager[Any]]
_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_SUMMARY_CHARS = 500
_SENSITIVE_KEYS = {
    "answer",
    "args",
    "content",
    "document",
    "documents",
    "notebook_context",
    "output",
    "prompt",
    "question",
    "raw_output",
    "text",
    "tool_args",
    "verified_context",
}


@dataclass(frozen=True)
class GraphFactRepositories:
    graph_runs: GraphRunRepository
    learning_events: LearningEventRepository
    tool_runs: ToolRunRepository
    attempts: AttemptRepository
    mastery_snapshots: MasterySnapshotRepository
    question_items: QuestionItemRepository
    concepts: ConceptRepository


def is_graph_facts_enabled() -> bool:
    raw = os.getenv("ENABLE_GRAPH_FACTS")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _TRUE_VALUES


def build_graph_fact_repositories(*, session_factory: SessionFactory = session_scope) -> GraphFactRepositories:
    return GraphFactRepositories(
        graph_runs=SqlGraphRunRepository(session_factory=session_factory),
        learning_events=SqlLearningEventRepository(session_factory=session_factory),
        tool_runs=SqlToolRunRepository(session_factory=session_factory),
        attempts=SqlAttemptRepository(session_factory=session_factory),
        mastery_snapshots=SqlMasterySnapshotRepository(session_factory=session_factory),
        question_items=SqlQuestionItemRepository(session_factory=session_factory),
        concepts=SqlConceptRepository(session_factory=session_factory),
    )


@dataclass(frozen=True)
class SqlGraphRunRepository(GraphRunRepository):
    session_factory: SessionFactory = session_scope

    def start_run(self, payload: dict[str, Any]) -> str:
        run_id = str(payload.get("id") or payload.get("run_id") or payload.get("graph_run_id") or uuid4())
        with self.session_factory() as session:
            existing = session.get(GraphRunModel, run_id)
            if existing is None:
                session.add(
                    GraphRunModel(
                        id=run_id,
                        graph_type=_text(payload.get("graph_type"), 40),
                        graph_version=_text(payload.get("graph_version"), 40),
                        run_name=_text(payload.get("run_name"), 120),
                        status=_text(payload.get("status") or "running", 30),
                        user_id=_text(payload.get("user_id"), 100),
                        tenant_id=_text(payload.get("tenant_id"), 100),
                        session_id=_text(payload.get("session_id"), 100),
                        thread_id=_text(payload.get("thread_id"), 100),
                        subject_id=_text(payload.get("subject_id") or payload.get("notebook_id") or "general", 64),
                        notebook_id=_text(payload.get("notebook_id"), 100),
                        source_policy=_text(payload.get("source_policy"), 40),
                        request_mode=_text(payload.get("request_mode"), 20),
                        langsmith_run_id=_text(payload.get("langsmith_run_id"), 160),
                        sampled=bool(payload.get("sampled", True)),
                        metadata_json=_summary(payload.get("metadata") or {}),
                        inputs_summary=_summary(payload.get("inputs_summary") or payload.get("inputs") or {}),
                    )
                )
            else:
                existing.status = _text(payload.get("status") or existing.status or "running", 30)
                if "langsmith_run_id" in payload:
                    existing.langsmith_run_id = _text(payload.get("langsmith_run_id"), 160)
                if "sampled" in payload:
                    existing.sampled = bool(payload.get("sampled", True))
                existing.metadata_json = _summary(payload.get("metadata") or existing.metadata_json or {})
                existing.inputs_summary = _summary(payload.get("inputs_summary") or existing.inputs_summary or {})
        return run_id

    def finish_run(self, graph_run_id: str, payload: dict[str, Any]) -> None:
        with self.session_factory() as session:
            row = session.get(GraphRunModel, graph_run_id)
            if row is None:
                row = GraphRunModel(
                    id=graph_run_id,
                    graph_type=_text(payload.get("graph_type"), 40),
                    graph_version=_text(payload.get("graph_version"), 40),
                    run_name=_text(payload.get("run_name"), 120),
                    user_id=_text(payload.get("user_id"), 100),
                    subject_id=_text(payload.get("subject_id") or "general", 64),
                    langsmith_run_id=_text(payload.get("langsmith_run_id"), 160),
                    sampled=bool(payload.get("sampled", True)),
                )
                session.add(row)
            row.status = _text(payload.get("status") or "completed", 30)
            row.outputs_summary = _summary(payload.get("outputs_summary") or payload.get("outputs") or {})
            row.error_type = _text(payload.get("error_type"), 120)
            if "langsmith_run_id" in payload:
                row.langsmith_run_id = _text(payload.get("langsmith_run_id"), 160)
            if "sampled" in payload:
                row.sampled = bool(payload.get("sampled", True))
            row.latency_ms = max(0, int(payload.get("latency_ms") or 0))
            row.ended_at = _utcnow()

    def record_audit_event(self, payload: dict[str, Any]) -> None:
        with self.session_factory() as session:
            session.add(
                NodeRunModel(
                    id=str(payload.get("id") or uuid4()),
                    graph_run_id=_text(payload.get("graph_run_id"), 100),
                    node_name=_text(payload.get("node_name") or payload.get("event_type") or "audit", 120),
                    status=_text(payload.get("status") or "completed", 30),
                    input_summary=_summary(payload.get("input_summary") or {}),
                    output_summary=_summary(payload.get("output_summary") or payload.get("payload") or {}),
                    error_type=_text(payload.get("error_type"), 120),
                    latency_ms=max(0, int(payload.get("latency_ms") or 0)),
                    ended_at=_utcnow(),
                )
            )


@dataclass(frozen=True)
class SqlLearningEventRepository(LearningEventRepository):
    session_factory: SessionFactory = session_scope

    def append(self, event: LearningEvent) -> str:
        payload = event.model_dump(mode="json")
        event_payload = _summary(payload.get("payload") or {})
        hash_key = _text(
            event_payload.get("hash_key")
            or learning_event_hash_key(
                event_type=event.event_type,
                user_id=event.user_id,
                concept_id=event.concept_id,
                payload=event_payload if isinstance(event_payload, dict) else {},
            ),
            128,
        )
        if hash_key and isinstance(event_payload, dict):
            event_payload.setdefault("hash_key", hash_key)
        with self.session_factory() as session:
            if not _session_can_flush(session):
                existing_id = _learning_event_existing_id(session, event_id=event.id, hash_key=hash_key)
                if existing_id:
                    return existing_id
            session.add(
                LearningEventModel(
                    id=event.id,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    concept_id=event.concept_id,
                    graph_run_id=event.graph_run_id,
                    hash_key=hash_key or None,
                    payload=event_payload,
                    created_at=_parse_datetime(event.created_at) or _utcnow(),
                )
            )
            try:
                _flush_session(session)
            except IntegrityError:
                session.rollback()
                existing_id = _learning_event_existing_id(session, event_id=event.id, hash_key=hash_key)
                if existing_id:
                    return existing_id
                raise
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(LearningEventModel)
                .where(LearningEventModel.user_id == user_id)
                .order_by(LearningEventModel.created_at.desc())
                .limit(_bounded_limit(limit))
            ).all()
            return [_event_from_row(row) for row in rows]


@dataclass(frozen=True)
class SqlToolRunRepository(ToolRunRepository):
    session_factory: SessionFactory = session_scope

    def record_tool_run(self, result: ToolResult, *, graph_run_id: str) -> str:
        run_id = str(uuid4())
        with self.session_factory() as session:
            session.add(
                ToolRunModel(
                    id=run_id,
                    graph_run_id=graph_run_id,
                    tool_id=result.tool_id,
                    provider=result.provider,
                    capability=result.capability.value,
                    status=result.status.value,
                    input_summary=_text(result.input_summary, _MAX_SUMMARY_CHARS),
                    output_summary=_summary(result.output),
                    evidence_refs=[
                        {
                            "id": evidence.id,
                            "source_type": evidence.source_type,
                            "source_id": evidence.source_id,
                            "score": evidence.score,
                        }
                        for evidence in result.evidence
                    ],
                    latency_ms=result.latency_ms,
                    error_type=_text(result.error, 120),
                )
            )
        return run_id


@dataclass(frozen=True)
class SqlAttemptRepository(AttemptRepository):
    session_factory: SessionFactory = session_scope

    def create_attempt(self, payload: dict[str, Any]) -> str:
        attempt_id = str(payload.get("id") or payload.get("attempt_id") or uuid4())
        concept_id = _text(payload.get("concept_id") or payload.get("knowledge_point"), 160)
        concept = get_concept_registry().get_concept(concept_id)
        if concept is None:
            logger.warning("Skip graph attempt with non-canonical concept_id: {}", concept_id)
            return ""
        with self.session_factory() as session:
            if not _session_can_flush(session):
                existing = session.get(GraphAttemptModel, attempt_id)
                if existing is not None:
                    return existing.id
            session.add(
                GraphAttemptModel(
                    id=attempt_id,
                    user_id=_text(payload.get("user_id"), 100),
                    subject_id=concept.subject_id,
                    concept_id=concept.concept_id,
                    question_id=_text(payload.get("question_id"), 100),
                    graph_run_id=_text(payload.get("graph_run_id"), 100),
                    source_event_id=_text(payload.get("source_event_id"), 100),
                    score=_optional_float(payload.get("score")),
                    is_correct=_optional_bool(payload.get("is_correct")),
                    payload=_summary(payload),
                    created_at=_parse_datetime(payload.get("created_at")) or _utcnow(),
                )
            )
            try:
                _flush_session(session)
            except IntegrityError:
                session.rollback()
                existing = session.get(GraphAttemptModel, attempt_id)
                if existing is not None:
                    return existing.id
                raise
        return attempt_id

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(GraphAttemptModel)
                .where(GraphAttemptModel.user_id == user_id)
                .order_by(GraphAttemptModel.created_at.desc())
                .limit(_bounded_limit(limit))
            ).all()
            return [_attempt_from_row(row) for row in rows]


@dataclass(frozen=True)
class SqlMasterySnapshotRepository(MasterySnapshotRepository):
    session_factory: SessionFactory = session_scope

    def upsert_snapshot(self, payload: dict[str, Any]) -> str:
        user_id = _text(payload.get("user_id"), 100)
        subject_id = _text(payload.get("subject_id") or "general", 64)
        concept_id = _text(payload.get("concept_id") or payload.get("knowledge_point"), 160)
        concept = get_concept_registry().get_concept(concept_id)
        if concept is None:
            logger.warning("Skip mastery snapshot with non-canonical concept_id: {}", concept_id)
            return ""
        subject_id = concept.subject_id
        concept_id = concept.concept_id
        snapshot_id = str(payload.get("id") or f"{user_id}:{subject_id}:{concept_id}")
        incoming_consumed = _string_list(payload.get("consumed_signal_ids") or payload.get("consumed_event_ids") or [])
        incoming_delta = _optional_float(payload.get("delta"))
        with self.session_factory() as session:
            row = _select_mastery_snapshot(
                session,
                user_id=user_id,
                subject_id=subject_id,
                concept_id=concept_id,
                for_update=True,
            )
            if row is None:
                p_mastery = _bounded_float(payload.get("p_mastery"), 0.5)
                row = MasterySnapshotModel(
                    id=snapshot_id,
                    user_id=user_id,
                    subject_id=subject_id,
                    concept_id=concept_id,
                    p_mastery=p_mastery,
                    status=_text(payload.get("status") or _status_for_mastery(p_mastery), 30),
                    evidence_ids=list(payload.get("evidence_ids") or []),
                    consumed_signal_ids=incoming_consumed,
                    version=1 if incoming_consumed else 0,
                    payload=_summary(payload),
                    created_at=_utcnow(),
                    updated_at=_parse_datetime(payload.get("updated_at")) or _utcnow(),
                )
                session.add(row)
                try:
                    _flush_session(session)
                except IntegrityError:
                    session.rollback()
                    row = _select_mastery_snapshot(
                        session,
                        user_id=user_id,
                        subject_id=subject_id,
                        concept_id=concept_id,
                        for_update=True,
                    )
                    if row is None:
                        raise
                    return _merge_mastery_snapshot_row(
                        row,
                        payload=payload,
                        incoming_consumed=incoming_consumed,
                        incoming_delta=incoming_delta,
                        snapshot_id=snapshot_id,
                    )
                return snapshot_id

            return _merge_mastery_snapshot_row(
                row,
                payload=payload,
                incoming_consumed=incoming_consumed,
                incoming_delta=incoming_delta,
                snapshot_id=snapshot_id,
            )

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(MasterySnapshotModel)
                .where(MasterySnapshotModel.user_id == user_id)
                .order_by(MasterySnapshotModel.updated_at.desc())
                .limit(_bounded_limit(limit))
            ).all()
            return [_snapshot_from_row(row) for row in rows]


@dataclass(frozen=True)
class SqlQuestionItemRepository(QuestionItemRepository):
    session_factory: SessionFactory = session_scope

    def create_question_item(self, payload: dict[str, Any]) -> str:
        item_id = str(payload.get("id") or payload.get("question_item_id") or uuid4())
        with self.session_factory() as session:
            existing = session.get(GraphQuestionItemModel, item_id)
            if existing is None:
                session.add(
                    GraphQuestionItemModel(
                        id=item_id,
                        user_id=_text(payload.get("user_id"), 100),
                        subject_id=_text(payload.get("subject_id") or "general", 64),
                        primary_concept_id=_text(payload.get("primary_concept_id") or payload.get("concept_id"), 160),
                        graph_run_id=_text(payload.get("graph_run_id"), 100),
                        stem=_text(payload.get("stem") or payload.get("question"), 4000),
                        options_json=_summary(payload.get("options") or payload.get("options_json") or []),
                        difficulty=_text(payload.get("difficulty") or "基础", 30),
                        source_refs=_summary(payload.get("source_refs") or []),
                        answer_key=_summary(payload.get("answer_key") or {}),
                        rubric=_summary(payload.get("rubric") or {}),
                        quality_report=_summary(payload.get("quality_report") or {}),
                        generation_source=_text(payload.get("generation_source"), 120),
                        metadata_json=_summary(payload.get("metadata") or {}),
                    )
                )
            else:
                existing.stem = _text(payload.get("stem") or payload.get("question") or existing.stem, 4000)
                existing.options_json = _summary(payload.get("options") or payload.get("options_json") or existing.options_json or [])
                existing.answer_key = _summary(payload.get("answer_key") or existing.answer_key or {})
                existing.rubric = _summary(payload.get("rubric") or existing.rubric or {})
                existing.quality_report = _summary(payload.get("quality_report") or existing.quality_report or {})
                existing.updated_at = _utcnow()
        return item_id

    def find_similar(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        stem = _text(payload.get("stem") or payload.get("question"), 4000)
        concept_id = _text(payload.get("primary_concept_id") or payload.get("concept_id"), 160)
        user_id = _text(payload.get("user_id"), 100)
        subject_id = _text(payload.get("subject_id") or payload.get("notebook_id"), 64)
        with self.session_factory() as session:
            query = select(GraphQuestionItemModel)
            if stem:
                query = query.where(GraphQuestionItemModel.stem == stem)
            elif concept_id:
                query = query.where(GraphQuestionItemModel.primary_concept_id == concept_id)
            else:
                return []
            if user_id:
                query = query.where(GraphQuestionItemModel.user_id == user_id)
            if subject_id:
                query = query.where(GraphQuestionItemModel.subject_id == subject_id)
            rows = session.scalars(query.order_by(GraphQuestionItemModel.created_at.desc()).limit(_bounded_limit(limit))).all()
            return [_question_item_from_row(row) for row in rows]


@dataclass(frozen=True)
class SqlConceptRepository(ConceptRepository):
    session_factory: SessionFactory = session_scope

    def resolve_concept(self, name: str) -> dict[str, Any] | None:
        normalized_name = _text(name, 240)
        if not normalized_name:
            return None
        with self.session_factory() as session:
            row = session.scalars(
                select(GraphConceptModel).where(GraphConceptModel.name == normalized_name)
            ).first()
            return _concept_from_row(row) if row is not None else None

    def upsert_concept(self, payload: dict[str, Any]) -> str:
        name = _text(payload.get("name"), 240)
        concept_id = _text(payload.get("concept_id") or payload.get("id") or name.lower(), 160)
        if not concept_id:
            concept_id = str(uuid4())
        with self.session_factory() as session:
            row = session.get(GraphConceptModel, concept_id)
            if row is None and name:
                row = session.scalars(select(GraphConceptModel).where(GraphConceptModel.name == name)).first()
            if row is None:
                row = GraphConceptModel(id=concept_id, name=name or concept_id)
                session.add(row)
            row.name = name or row.name
            row.subject_id = _text(payload.get("subject_id") or row.subject_id or "general", 64)
            row.aliases = _summary(payload.get("aliases") or row.aliases or [])
            row.source = _text(payload.get("source") or row.source or "graph", 80)
            row.metadata_json = _summary(payload.get("metadata") or row.metadata_json or {})
            row.updated_at = _utcnow()
        return concept_id


@dataclass(frozen=True)
class CompositeAttemptRepository(AttemptRepository):
    primary: AttemptRepository
    legacy: AttemptRepository | None = None

    def create_attempt(self, payload: dict[str, Any]) -> str:
        return self.primary.create_attempt(payload)

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for repository in [self.primary, self.legacy]:
            if repository is None:
                continue
            for attempt in repository.list_recent_attempts(user_id=user_id, limit=limit):
                attempt_id = str(attempt.get("attempt_id") or attempt.get("id") or "")
                if attempt_id and attempt_id in seen:
                    continue
                if attempt_id:
                    seen.add(attempt_id)
                merged.append(attempt)
                if len(merged) >= _bounded_limit(limit):
                    return merged
        return merged


@dataclass(frozen=True)
class CompositeMasterySnapshotRepository(MasterySnapshotRepository):
    primary: MasterySnapshotRepository
    legacy: MasterySnapshotRepository | None = None

    def upsert_snapshot(self, payload: dict[str, Any]) -> str:
        return self.primary.upsert_snapshot(payload)

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for repository in [self.primary, self.legacy]:
            if repository is None:
                continue
            for snapshot in repository.list_snapshots(user_id=user_id, limit=limit):
                key = (
                    str(snapshot.get("user_id") or ""),
                    str(snapshot.get("subject_id") or "general"),
                    str(snapshot.get("concept_id") or snapshot.get("knowledge_point") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(snapshot)
                if len(merged) >= _bounded_limit(limit):
                    return merged
        return merged


def _learning_event_existing_id(session: Any, *, event_id: str, hash_key: str) -> str:
    if hash_key:
        existing_by_hash = session.scalars(
            select(LearningEventModel.id).where(LearningEventModel.hash_key == hash_key)
        ).first()
        if existing_by_hash:
            return str(existing_by_hash)
    existing_by_id = session.get(LearningEventModel, event_id)
    return str(existing_by_id.id) if existing_by_id is not None else ""


def _session_can_flush(session: Any) -> bool:
    return callable(getattr(session, "flush", None))


def _flush_session(session: Any) -> None:
    flush = getattr(session, "flush", None)
    if callable(flush):
        flush()


def _select_mastery_snapshot(
    session: Any,
    *,
    user_id: str,
    subject_id: str,
    concept_id: str,
    for_update: bool,
) -> MasterySnapshotModel | None:
    stmt = select(MasterySnapshotModel).where(
        MasterySnapshotModel.user_id == user_id,
        MasterySnapshotModel.subject_id == subject_id,
        MasterySnapshotModel.concept_id == concept_id,
    )
    get_bind = getattr(session, "get_bind", None)
    dialect_name = get_bind().dialect.name if callable(get_bind) else ""
    if for_update and dialect_name == "postgresql":
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def _merge_mastery_snapshot_row(
    row: MasterySnapshotModel,
    *,
    payload: dict[str, Any],
    incoming_consumed: list[str],
    incoming_delta: float | None,
    snapshot_id: str,
) -> str:
    existing_consumed = _string_list(row.consumed_signal_ids or [])
    existing_consumed_set = set(existing_consumed)
    new_consumed = [item for item in incoming_consumed if item not in existing_consumed_set]
    if incoming_consumed and not new_consumed:
        return row.id or snapshot_id

    if incoming_consumed and incoming_delta is not None:
        effective_delta = incoming_delta * (len(new_consumed) / max(1, len(incoming_consumed)))
        row.p_mastery = _bounded_float(float(row.p_mastery or 0.5) + effective_delta, 0.5)
        row.status = _text(_status_for_mastery(row.p_mastery), 30)
    else:
        row.p_mastery = _bounded_float(payload.get("p_mastery"), float(row.p_mastery or 0.5))
        row.status = _text(payload.get("status") or _status_for_mastery(row.p_mastery), 30)
    row.evidence_ids = _merge_string_lists(row.evidence_ids or [], payload.get("evidence_ids") or [])
    row.consumed_signal_ids = _merge_string_lists(existing_consumed, new_consumed)
    row.version = int(row.version or 0) + 1
    row.payload = _summary(payload)
    row.updated_at = _parse_datetime(payload.get("updated_at")) or _utcnow()
    return row.id or snapshot_id


def _event_from_row(row: LearningEventModel) -> LearningEvent:
    payload = dict(row.payload or {})
    if row.hash_key:
        payload.setdefault("hash_key", row.hash_key)
    return LearningEvent(
        id=row.id,
        event_type=row.event_type,
        user_id=row.user_id,
        concept_id=row.concept_id,
        graph_run_id=row.graph_run_id,
        payload=payload,
        created_at=_iso(row.created_at),
    )


def _attempt_from_row(row: GraphAttemptModel) -> dict[str, Any]:
    payload = dict(row.payload or {})
    return {
        **payload,
        "attempt_id": row.id,
        "id": row.id,
        "user_id": row.user_id,
        "subject_id": row.subject_id,
        "concept_id": row.concept_id,
        "knowledge_point": row.concept_id,
        "question_id": row.question_id,
        "graph_run_id": row.graph_run_id,
        "source_event_id": row.source_event_id,
        "score": row.score,
        "is_correct": row.is_correct,
        "created_at": _iso(row.created_at),
    }


def _snapshot_from_row(row: MasterySnapshotModel) -> dict[str, Any]:
    payload = dict(row.payload or {})
    return {
        **payload,
        "id": row.id,
        "user_id": row.user_id,
        "subject_id": row.subject_id,
        "concept_id": row.concept_id,
        "knowledge_point": row.concept_id,
        "p_mastery": row.p_mastery,
        "status": row.status,
        "evidence_ids": list(row.evidence_ids or []),
        "consumed_signal_ids": list(row.consumed_signal_ids or []),
        "version": int(row.version or 0),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _question_item_from_row(row: GraphQuestionItemModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "subject_id": row.subject_id,
        "primary_concept_id": row.primary_concept_id,
        "graph_run_id": row.graph_run_id,
        "stem": row.stem,
        "options": list(row.options_json or []),
        "difficulty": row.difficulty,
        "source_refs": list(row.source_refs or []),
        "answer_key": dict(row.answer_key or {}),
        "rubric": dict(row.rubric or {}),
        "quality_report": dict(row.quality_report or {}),
        "generation_source": row.generation_source,
        "metadata": dict(row.metadata_json or {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _concept_from_row(row: GraphConceptModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "concept_id": row.id,
        "name": row.name,
        "subject_id": row.subject_id,
        "aliases": list(row.aliases or []),
        "source": row.source,
        "metadata": dict(row.metadata_json or {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _summary(value: Any, *, depth: int = 5) -> Any:
    if depth <= 0:
        return "<truncated-depth>"
    if isinstance(value, dict):
        summarized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_KEYS:
                summarized[str(key)] = _summarize_sensitive(item)
            else:
                summarized[str(key)] = _summary(item, depth=depth - 1)
        return summarized
    if isinstance(value, list):
        if len(value) > 5:
            return {"count": len(value), "preview": [_summary(item, depth=depth - 1) for item in value[:2]]}
        return [_summary(item, depth=depth - 1) for item in value]
    if isinstance(value, str):
        return _text(value, _MAX_SUMMARY_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return _iso(value)
    return _text(str(value), _MAX_SUMMARY_CHARS)


def _summarize_sensitive(value: Any) -> Any:
    if isinstance(value, str):
        return {"char_count": len(value)}
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, dict):
        return {"keys": sorted(str(key) for key in value.keys())}
    return "<redacted>"


def _text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3]}..."


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 100
    return max(1, min(value, 500))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_float(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        parsed = default
    return max(0.0, min(1.0, parsed))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_string_lists(first: Any, second: Any) -> list[str]:
    merged: list[str] = []
    for item in [*_string_list(first), *_string_list(second)]:
        if item not in merged:
            merged.append(item)
    return merged


def _status_for_mastery(value: float) -> str:
    if value >= 0.8:
        return "mastered"
    if value >= 0.5:
        return "learning"
    return "weak"


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return bool(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        candidate = value
    else:
        try:
            candidate = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    candidate = _parse_datetime(value)
    return (candidate or _utcnow()).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
