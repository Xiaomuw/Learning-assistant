from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import PracticeAttemptModel
from app.infrastructure.db.repositories._shared import serialize_practice_attempt_record
from app.infrastructure.db.repositories.knowledge_stats import (
    list_knowledge_mastery_records,
    record_knowledge_exposure,
)
from app.orchestration.graphs.mastery.schemas import MasterySnapshot
from app.persistence.interfaces import AttemptRepository, MasterySnapshotRepository


@dataclass(frozen=True)
class LegacyPracticeAttemptRepository(AttemptRepository):
    """Read adapter from existing ``practice_attempts`` into MasteryGraph."""

    subject_id: str | None = None

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with session_scope() as session:
            stmt = select(PracticeAttemptModel).where(PracticeAttemptModel.user_id == user_id)
            if self.subject_id:
                stmt = stmt.where(PracticeAttemptModel.subject_id == self.subject_id)
            stmt = stmt.order_by(PracticeAttemptModel.created_at.desc()).limit(max(1, min(int(limit or 100), 200)))
            rows = session.scalars(stmt).all()
            return [_attempt_record_to_mastery_payload(row) for row in rows]

    def create_attempt(self, payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("attempt_id") or "")


@dataclass(frozen=True)
class LegacyKnowledgeStatsMasteryRepository(MasterySnapshotRepository):
    """Adapter from graph-era mastery snapshots to existing knowledge stats."""

    allow_writes: bool = False
    subject_id: str | None = None

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        records = list_knowledge_mastery_records(user_id=user_id, subject_id=self.subject_id, limit=limit)
        snapshots: list[dict[str, Any]] = []
        for record in records:
            score = float(record.mastery_score or 0.0)
            snapshots.append(
                {
                    "id": f"{record.user_id}:{record.subject_id}:{record.knowledge_point}",
                    "user_id": record.user_id,
                    "subject_id": record.subject_id,
                    "concept_id": record.knowledge_point,
                    "knowledge_point": record.knowledge_point,
                    "p_mastery": max(0.0, min(1.0, score / 100.0)),
                    "mastery_score": record.mastery_score,
                    "status": record.mastery_level,
                    "exposure_count": record.exposure_count,
                    "attempt_count": record.attempt_count,
                    "correct_count": record.correct_count,
                    "wrong_count": record.wrong_count,
                    "evidence_ids": [],
                    "last_seen_at": record.last_seen_at,
                    "last_practiced_at": record.last_practiced_at,
                    "updated_at": record.updated_at,
                }
            )
        return snapshots

    def upsert_snapshot(self, payload: dict[str, Any]) -> str:
        snapshot = MasterySnapshot.model_validate(payload)
        snapshot_id = f"{snapshot.user_id}:{snapshot.subject_id}:{snapshot.concept_id}"
        if self.allow_writes:
            record_knowledge_exposure(
                user_id=snapshot.user_id,
                subject_id=snapshot.subject_id,
                knowledge_point=snapshot.concept_id,
                count=1,
            )
        return snapshot_id


def _attempt_record_to_mastery_payload(row: PracticeAttemptModel) -> dict[str, Any]:
    record = serialize_practice_attempt_record(row)
    return {
        "attempt_id": record.id,
        "id": record.id,
        "user_id": record.user_id,
        "session_id": record.session_id,
        "subject_id": record.subject_id,
        "question_id": record.question_id,
        "question_snapshot": record.question_snapshot,
        "selected_option": record.selected_option,
        "is_correct": record.is_correct,
        "knowledge_point": record.knowledge_point,
        "concept_id": record.knowledge_point,
        "source_type": record.source_type,
        "created_at": record.created_at,
    }
