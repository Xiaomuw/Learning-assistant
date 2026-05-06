from __future__ import annotations

from typing import Any

from app.orchestration.graphs.shared.state import BaseLearningState


class MasteryEvaluationState(BaseLearningState, total=False):
    attempt_payloads: list[dict[str, Any]]
    history_snapshots: list[dict[str, Any]]
    consumed_event_ids: list[str]
    consumed_signal_ids: list[str]
    mastery_evidence: list[dict[str, Any]]
    aggregated_evidence: list[dict[str, Any]]
    ignored_weak_signal_ids: list[str]
    mastery_updates: list[dict[str, Any]]
    mastery_snapshots: list[dict[str, Any]]
    mastery_snapshot_ids: list[str]
    next_learning_actions: list[dict[str, Any]]
    output_learning_events: list[dict[str, Any]]
