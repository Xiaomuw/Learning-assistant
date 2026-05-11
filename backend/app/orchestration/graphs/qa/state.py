from __future__ import annotations

from typing import Any

from app.orchestration.graphs.shared.state import BaseLearningState


class QAGraphState(BaseLearningState, total=False):
    question_type: str
    normalized_question: str
    context_dependency: dict[str, Any]
    intent_result: dict[str, Any]
    parent_intent_decision: dict[str, Any]
    intent_alignment: dict[str, Any]
    resolved_question: str
    concept_linking: dict[str, Any]
    knowledge_routes: list[dict[str, Any]]
    retrieval_skipped_reason: str
    notebook_evidence: list[dict[str, Any]]
    web_evidence: list[dict[str, Any]]
    evidence_judgement: dict[str, Any]
    quality_check: dict[str, Any]
    answer_quality: dict[str, Any]
    repair_count: int
    max_repair_count: int
    answer_repair_attempt_count: int
    source_usage: str
    web_search_attempted: bool
    web_search_reason: str
    web_search_iteration: int
    retrieval_report: dict[str, Any]
    memory: dict[str, Any]
    session_memory: dict[str, Any]
    available_knowledge_bases: list[dict[str, Any]]
    knowledge_bases: list[dict[str, Any]]
    qa_request: dict[str, Any]
    evidence_gate: dict[str, Any]
    grounding_report: dict[str, Any]
    tool_requests: list[dict[str, Any]]
    adapter_learning_events: list[dict[str, Any]]
    runtime_summary: dict[str, Any]
    persisted_learning_event_ids: list[str]
