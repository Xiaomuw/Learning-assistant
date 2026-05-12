"""Enterprise graph baseline schemas.

These contracts are shared by orchestration graph skeletons, tool abstractions
and future persistence adapters. Keep them serializable and runtime-agnostic.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class GraphType(StrEnum):
    ORCHESTRATOR = "orchestrator"
    QA = "qa"
    QUESTION_GENERATION = "question_generation"
    MASTERY = "mastery"


class SourcePolicy(StrEnum):
    NOTEBOOK_ONLY = "notebook_only"
    NOTEBOOK_PLUS_EXTERNAL = "notebook_plus_external"
    OPEN_TOOLS = "open_tools"


class SourceLevel(StrEnum):
    NONE = "none"
    MODEL = "model"
    NOTEBOOK = "notebook"
    WEB = "web"
    MIXED = "mixed"


class ToolCapability(StrEnum):
    NOTEBOOK_RETRIEVE = "notebook_retrieve"
    WEB_SEARCH = "web_search"
    WEB_EXTRACT = "web_extract"
    SQL_READ = "sql_read"
    CODE_EXECUTE = "code_execute"
    FILE_PARSE = "file_parse"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class LearningEventType(StrEnum):
    PRACTICE_ATTEMPT_SUBMITTED = "practice_attempt_submitted"
    ATTEMPT_SCORED = "attempt_scored"
    QUESTION_ANSWERED = "question_answered"
    CONCEPT_EXPLAINED = "concept_explained"
    EVIDENCE_USED = "evidence_used"
    TOOL_FALLBACK_USED = "tool_fallback_used"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ANSWER_REPAIRED = "answer_repaired"
    MISCONCEPTION_DETECTED = "misconception_detected"
    HINT_REQUESTED = "hint_requested"
    STUCK_REPORTED = "stuck_reported"
    QUESTION_GENERATED = "question_generated"
    QUESTION_REVIEWED = "question_reviewed"
    QUESTION_GENERATION_DEGRADED = "question_generation_degraded"
    QUESTION_GENERATION_FAILED = "question_generation_failed"
    MASTERY_UPDATED = "mastery_updated"
    NEXT_STEP_RECOMMENDED = "next_step_recommended"


QA_LEARNING_EVENT_TYPES: frozenset[str] = frozenset(
    {
        LearningEventType.QUESTION_ANSWERED.value,
        LearningEventType.CONCEPT_EXPLAINED.value,
        LearningEventType.EVIDENCE_USED.value,
        LearningEventType.TOOL_FALLBACK_USED.value,
        LearningEventType.INSUFFICIENT_EVIDENCE.value,
        LearningEventType.ANSWER_REPAIRED.value,
    }
)

QUESTION_GENERATION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        LearningEventType.QUESTION_GENERATED.value,
        LearningEventType.QUESTION_REVIEWED.value,
        LearningEventType.QUESTION_GENERATION_DEGRADED.value,
        LearningEventType.QUESTION_GENERATION_FAILED.value,
    }
)

MASTERY_CONSUMABLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        LearningEventType.PRACTICE_ATTEMPT_SUBMITTED.value,
        LearningEventType.ATTEMPT_SCORED.value,
        LearningEventType.QUESTION_ANSWERED.value,
        LearningEventType.CONCEPT_EXPLAINED.value,
        LearningEventType.EVIDENCE_USED.value,
        LearningEventType.TOOL_FALLBACK_USED.value,
        LearningEventType.INSUFFICIENT_EVIDENCE.value,
        LearningEventType.ANSWER_REPAIRED.value,
        LearningEventType.MISCONCEPTION_DETECTED.value,
        LearningEventType.HINT_REQUESTED.value,
        LearningEventType.STUCK_REPORTED.value,
    }
)

MASTERY_OUTPUT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        LearningEventType.MASTERY_UPDATED.value,
        LearningEventType.NEXT_STEP_RECOMMENDED.value,
    }
)


class GraphErrorSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_event_id() -> str:
    return str(uuid4())


def learning_event_hash_key(
    *,
    event_type: str,
    user_id: str,
    concept_id: str | None = None,
    source_object_type: str = "",
    source_object_id: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    payload = dict(payload or {})
    source_type = str(
        source_object_type
        or payload.get("source_object_type")
        or payload.get("source_type")
        or payload.get("object_type")
        or ""
    ).strip()
    source_id = str(
        source_object_id
        or payload.get("source_object_id")
        or payload.get("source_event_id")
        or payload.get("attempt_id")
        or payload.get("question_item_id")
        or payload.get("question_id")
        or payload.get("message_id")
        or ""
    ).strip()
    if not event_type or not user_id or not source_type or not source_id:
        return ""
    parts = [
        str(event_type).strip(),
        str(user_id).strip(),
        str(concept_id or payload.get("concept_id") or "").strip(),
        source_type,
        source_id,
    ]
    raw = ":".join(parts)
    if len(raw) <= 128:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{parts[0]}:{digest[:32]}"


def build_learning_event(
    *,
    event_type: str,
    user_id: str,
    graph_run_id: str,
    concept_id: str | None = None,
    payload: dict[str, Any] | None = None,
    source_object_type: str = "",
    source_object_id: str = "",
) -> "LearningEvent":
    event_payload = dict(payload or {})
    if source_object_type:
        event_payload.setdefault("source_object_type", source_object_type)
    if source_object_id:
        event_payload.setdefault("source_object_id", source_object_id)
    hash_key = learning_event_hash_key(
        event_type=event_type,
        user_id=user_id,
        concept_id=concept_id,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        payload=event_payload,
    )
    if hash_key:
        event_payload.setdefault("hash_key", hash_key)
    return LearningEvent(
        event_type=event_type,
        user_id=user_id,
        concept_id=concept_id,
        graph_run_id=graph_run_id,
        payload=event_payload,
    )


class ConceptRef(BaseModel):
    concept_id: str = ""
    name: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = ""


class EvidenceChunk(BaseModel):
    id: str = Field(default_factory=new_event_id)
    source_type: str = ""
    source_id: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    concepts: list[ConceptRef] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool_id: str
    provider: str
    capability: ToolCapability
    status: ToolStatus
    input_summary: str = ""
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)
    error: str = ""


class LearningEvent(BaseModel):
    id: str = Field(default_factory=new_event_id)
    event_type: str
    user_id: str
    concept_id: str | None = None
    graph_run_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class FinalResponse(BaseModel):
    answer: str = ""
    source_level: SourceLevel = SourceLevel.NONE
    concepts: list[ConceptRef] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    coach_actions: list[str] = Field(default_factory=list)
    mastery_signals: dict[str, Any] = Field(default_factory=dict)
    ui_payload: dict[str, Any] = Field(default_factory=dict)


class GraphError(BaseModel):
    code: str
    message: str
    node: str = ""
    severity: GraphErrorSeverity = GraphErrorSeverity.ERROR
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphVersionInfo(BaseModel):
    graph_version: str = "0.1.0"
    prompt_version: str = "0.1.0"
    model_version: str = ""
    tool_version: str = "0.1.0"
