from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from loguru import logger

from app.orchestration.graphs.mastery.graph import build_production_graph as build_mastery_graph
from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
from app.shared.schemas.agent_graphs import LearningEvent, LearningEventType
from app.shared.schemas.contracts import PracticeRecommendation, PracticeSubmissionResult
from app.shared.schemas.subject import normalize_subject_id


_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_graph_dual_write_enabled() -> bool:
    return str(os.getenv("ENABLE_GRAPH_DUAL_WRITE", "")).strip().lower() in _TRUE_VALUES


def maybe_dual_write_practice_attempt(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    result: PracticeSubmissionResult,
) -> None:
    if not (is_graph_dual_write_enabled() and is_graph_facts_enabled()):
        return
    try:
        _dual_write_practice_attempt(
            user_id=user_id,
            session_id=session_id,
            subject_id=subject_id,
            quiz_item=quiz_item,
            selected_option=selected_option,
            result=result,
        )
    except Exception as exc:  # pragma: no cover - dual-write must not affect user response
        logger.warning(f"Graph practice dual-write failed open: {exc.__class__.__name__}")


def _dual_write_practice_attempt(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    result: PracticeSubmissionResult,
) -> None:
    repos = build_graph_fact_repositories()
    normalized_subject_id = normalize_subject_id(subject_id)
    concept_id = quiz_item.knowledge_point or "综合"
    graph_run_id = f"practice-attempt-{uuid4()}"
    attempt_id = f"attempt-{uuid4()}"
    submitted = LearningEvent(
        event_type=LearningEventType.PRACTICE_ATTEMPT_SUBMITTED.value,
        user_id=user_id,
        concept_id=concept_id,
        graph_run_id=graph_run_id,
        payload={
            "session_id": session_id,
            "subject_id": normalized_subject_id,
            "question_id": quiz_item.question_id,
            "concept_id": concept_id,
            "selected_option": selected_option.strip().upper()[:1],
            "is_correct": result.is_correct,
        },
    )
    scored = LearningEvent(
        event_type=LearningEventType.ATTEMPT_SCORED.value,
        user_id=user_id,
        concept_id=concept_id,
        graph_run_id=graph_run_id,
        payload={
            "subject_id": normalized_subject_id,
            "question_id": quiz_item.question_id,
            "concept_id": concept_id,
            "is_correct": result.is_correct,
            "score": 1.0 if result.is_correct else 0.0,
            "mastery_score": result.mastery_evaluation.mastery_score if result.mastery_evaluation else None,
            "mastery_level": result.mastery_evaluation.mastery_level if result.mastery_evaluation else "",
        },
    )
    repos.graph_runs.start_run(
        {
            "run_id": graph_run_id,
            "graph_type": "mastery",
            "run_name": "practice.dual_write",
            "status": "completed",
            "user_id": user_id,
            "session_id": session_id,
            "subject_id": normalized_subject_id,
            "request_mode": "practice_attempt",
            "inputs_summary": {
                "question_id": quiz_item.question_id,
                "concept_id": concept_id,
                "selected_option_present": bool(selected_option),
            },
        }
    )
    repos.learning_events.append(submitted)
    repos.learning_events.append(scored)
    repos.attempts.create_attempt(
        {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "subject_id": normalized_subject_id,
            "concept_id": concept_id,
            "knowledge_point": concept_id,
            "question_id": quiz_item.question_id,
            "graph_run_id": graph_run_id,
            "source_event_id": scored.id,
            "score": 1.0 if result.is_correct else 0.0,
            "is_correct": result.is_correct,
            "session_id": session_id,
        }
    )
    mastery_output = build_mastery_graph(subject_id=normalized_subject_id).compile().invoke(
        {
            "run_id": graph_run_id,
            "user_id": user_id,
            "notebook_id": normalized_subject_id,
            "learning_events": [submitted.model_dump(mode="json"), scored.model_dump(mode="json")],
            "attempt_payloads": [
                {
                    "attempt_id": attempt_id,
                    "user_id": user_id,
                    "subject_id": normalized_subject_id,
                    "concept_id": concept_id,
                    "question_id": quiz_item.question_id,
                    "is_correct": result.is_correct,
                    "score": 1.0 if result.is_correct else 0.0,
                }
            ],
        }
    )
    repos.graph_runs.finish_run(
        graph_run_id,
        {
            "status": "completed",
            "outputs_summary": {
                "learning_event_count": 2,
                "attempt_written": True,
                "mastery_snapshot_count": len(list(mastery_output.get("mastery_snapshot_ids") or [])),
            },
        },
    )
