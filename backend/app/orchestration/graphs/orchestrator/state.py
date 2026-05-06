from __future__ import annotations

from typing import Any

from app.orchestration.graphs.shared.state import BaseLearningState


class OrchestratorState(BaseLearningState, total=False):
    runtime_context: dict[str, Any]
    chat_runtime_context: dict[str, Any]
    production_runtime: bool
    learner_context: dict[str, Any]
    intent_decision: dict[str, Any]
    quiz_request: dict[str, Any]
    quiz_clarification: dict[str, Any]
    child_graph_output: dict[str, Any]
    audit_events: list[dict[str, Any]]
