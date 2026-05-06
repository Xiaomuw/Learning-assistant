from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.orchestration.graphs.shared.schemas import new_event_id, utc_now_iso


class SignalStrength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


class MasteryStatus(StrEnum):
    WEAK = "weak"
    LEARNING = "learning"
    MASTERED = "mastered"


class MasteryEvidence(BaseModel):
    id: str = Field(default_factory=new_event_id)
    signal_id: str
    signal_source: str
    user_id: str
    concept_id: str
    subject_id: str = "general"
    strength: SignalStrength
    observed_score: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    hint_used: bool = False
    hint_count: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class MasteryUpdate(BaseModel):
    concept_id: str
    user_id: str
    subject_id: str = "general"
    previous_p_mastery: float = Field(default=0.5, ge=0.0, le=1.0)
    p_mastery: float = Field(default=0.5, ge=0.0, le=1.0)
    delta: float
    evidence_ids: list[str] = Field(default_factory=list)
    consumed_signal_ids: list[str] = Field(default_factory=list)
    status: MasteryStatus = MasteryStatus.LEARNING


class MasterySnapshot(BaseModel):
    id: str = Field(default_factory=new_event_id)
    user_id: str
    concept_id: str
    subject_id: str = "general"
    p_mastery: float = Field(ge=0.0, le=1.0)
    status: MasteryStatus
    evidence_ids: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


class NextLearningAction(BaseModel):
    concept_id: str
    action_type: str
    priority: int = Field(default=1, ge=1, le=5)
    reason: str = ""


class MasteryEvaluationInput(BaseModel):
    user_id: str
    learning_event_ids: list[str] = Field(default_factory=list)
    learning_events: list[dict[str, Any]] = Field(default_factory=list)
    attempt_payloads: list[dict[str, Any]] = Field(default_factory=list)
    history_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    consumed_signal_ids: list[str] = Field(default_factory=list)


class MasteryEvaluationOutput(BaseModel):
    mastery_snapshot_ids: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    mastery_updates: list[MasteryUpdate] = Field(default_factory=list)
    next_actions: list[NextLearningAction] = Field(default_factory=list)
