from __future__ import annotations

from typing import Any

from app.orchestration.graphs.shared.state import BaseLearningState


class QuestionGenerationState(BaseLearningState, total=False):
    quiz_request: dict[str, Any]
    count: int
    requested_count: int
    difficulty: str
    question_type: str
    generation_blueprint: dict[str, Any]
    source_refs: list[dict[str, Any]]
    question_candidates: list[dict[str, Any]]
    solver_report: dict[str, Any]
    quality_report: dict[str, Any]
    question_items: list[dict[str, Any]]
    question_item_ids: list[str]
    generation_status: dict[str, Any]
