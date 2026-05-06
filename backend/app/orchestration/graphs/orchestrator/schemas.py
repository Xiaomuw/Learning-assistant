from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.orchestration.graphs.shared.schemas import GraphType


class OrchestratorIntent(StrEnum):
    QA = "qa"
    GENERATE_QUESTION = "generate_question"
    EVALUATE_MASTERY = "evaluate_mastery"
    FALLBACK = "fallback"


class IntentDecision(BaseModel):
    intent: OrchestratorIntent
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    target_graph_type: GraphType


class ChildGraphOutput(BaseModel):
    target_graph_type: GraphType
    payload: dict[str, Any] = Field(default_factory=dict)

