from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.persistence.repositories.mastery import (
    LegacyKnowledgeStatsMasteryRepository,
    LegacyPracticeAttemptRepository,
)


@dataclass(frozen=True)
class EmptyLegacyLearningEventRepository:
    """Read adapter placeholder until learning_events has a durable table."""

    def list_for_user(self, *, user_id: str, limit: int = 100):
        _ = user_id, limit
        return []

    def append(self, event):
        return event.id


@dataclass(frozen=True)
class EmptyLegacyAttemptRepository:
    """Read adapter placeholder because attempts currently lack a list repository."""

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        _ = user_id, limit
        return []

    def create_attempt(self, payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("attempt_id") or "")
