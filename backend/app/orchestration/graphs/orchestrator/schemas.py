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


class ChildGraphResult(BaseModel):
    """Canonical child graph boundary contract consumed by the Orchestrator."""

    task_type: str
    status: str = "succeeded"
    content: dict[str, Any] = Field(default_factory=dict)
    learning_events: list[dict[str, Any]] = Field(default_factory=list)
    audit_event: dict[str, Any] = Field(default_factory=dict)
    ui_payload: dict[str, Any] = Field(default_factory=dict)
    trace_steps: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class ResponseEnvelope(BaseModel):
    """Unified Orchestrator projection for sync payloads and SSE event plans."""

    explanation: dict[str, Any] = Field(default_factory=dict)
    quiz: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    final: dict[str, Any] = Field(default_factory=dict)
    sse_events: list[dict[str, Any]] = Field(default_factory=list)
    sync_payload: dict[str, Any] = Field(default_factory=dict)
