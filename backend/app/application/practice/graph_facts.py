from __future__ import annotations

import hashlib
import os
from typing import Any

from loguru import logger

from app.knowledge.concept_registry import get_concept_registry
from app.orchestration.graphs.mastery.graph import (
    build_graph as build_mastery_graph_with_repositories,
    build_production_graph as build_mastery_graph,
)
from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
from app.shared.schemas.agent_graphs import LearningEventType, build_learning_event
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


def update_graph_mastery_from_practice_attempt(
    *,
    legacy_attempt: Any,
    user_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    is_correct: bool,
) -> None:
    if not is_graph_facts_enabled():
        return
    concept_id = str(quiz_item.concept_id or "").strip()
    concept = get_concept_registry().get_concept(concept_id)
    if concept is None:
        return

    legacy_attempt_id = _value_from_record(legacy_attempt, "id")
    if not legacy_attempt_id:
        return

    graph_attempt_id = graph_attempt_id_for_practice_attempt(legacy_attempt_id)
    payload = {
        "id": graph_attempt_id,
        "attempt_id": graph_attempt_id,
        "user_id": user_id,
        "subject_id": subject_id or concept.subject_id,
        "concept_id": concept.concept_id,
        "knowledge_point": concept.concept_id,
        "concept_name": concept.concept_name,
        "chapter_id": concept.chapter_id,
        "topic_id": concept.topic_id,
        "question_id": str(quiz_item.question_id or ""),
        "selected_option": selected_option,
        "correct_option": quiz_item.correct_option,
        "is_correct": bool(is_correct),
        "score": 1.0 if is_correct else 0.0,
        "confidence": 1.0,
        "source": "practice_attempt",
        "source_event_id": legacy_attempt_id,
        "created_at": _value_from_record(legacy_attempt, "created_at"),
    }
    try:
        repos = build_graph_fact_repositories()
        repos.attempts.create_attempt(payload)
        build_mastery_graph_with_repositories(
            learning_event_repository=repos.learning_events,
            attempt_repository=None,
            mastery_repository=repos.mastery_snapshots,
        ).compile().invoke(
            {
                "run_id": f"practice-mastery:{legacy_attempt_id}",
                "user_id": user_id,
                "notebook_id": subject_id or concept.subject_id,
                "attempt_payloads": [payload],
            }
        )
    except Exception as exc:
        logger.warning(
            "Graph-era mastery update failed open for practice attempt {}: {}",
            legacy_attempt_id,
            exc.__class__.__name__,
        )


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
    concept_id = quiz_item.concept_id or quiz_item.knowledge_point or "综合"
    concept_name = quiz_item.concept_name or quiz_item.knowledge_point or concept_id
    attempt_id = stable_graph_attempt_id_for_practice_submission(
        user_id=user_id,
        session_id=session_id,
        subject_id=normalized_subject_id,
        question_id=str(quiz_item.question_id or ""),
    )
    graph_run_id = f"practice-attempt-{attempt_id}"
    submitted = build_learning_event(
        event_type=LearningEventType.PRACTICE_ATTEMPT_SUBMITTED.value,
        user_id=user_id,
        concept_id=concept_id,
        graph_run_id=graph_run_id,
        source_object_type="practice_attempt",
        source_object_id=attempt_id,
        payload={
            "session_id": session_id,
            "subject_id": normalized_subject_id,
            "attempt_id": attempt_id,
            "question_id": quiz_item.question_id,
            "concept_id": concept_id,
            "concept_name": concept_name,
            "chapter_id": quiz_item.chapter_id,
            "topic_id": quiz_item.topic_id,
            "selected_option": selected_option.strip().upper()[:1],
            "is_correct": result.is_correct,
        },
    )
    scored = build_learning_event(
        event_type=LearningEventType.ATTEMPT_SCORED.value,
        user_id=user_id,
        concept_id=concept_id,
        graph_run_id=graph_run_id,
        source_object_type="practice_attempt",
        source_object_id=attempt_id,
        payload={
            "subject_id": normalized_subject_id,
            "attempt_id": attempt_id,
            "question_id": quiz_item.question_id,
            "concept_id": concept_id,
            "concept_name": concept_name,
            "chapter_id": quiz_item.chapter_id,
            "topic_id": quiz_item.topic_id,
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
            "knowledge_point": concept_name,
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
                    "concept_name": concept_name,
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


def _value_from_record(record: Any, key: str) -> str:
    if isinstance(record, dict):
        value = record.get(key)
    else:
        value = getattr(record, key, "")
    return str(value or "").strip()


def graph_attempt_id_for_practice_attempt(legacy_attempt_id: str) -> str:
    graph_attempt_id = f"practice:{legacy_attempt_id}"
    if len(graph_attempt_id) <= 100:
        return graph_attempt_id

    return f"practice:{hashlib.sha1(legacy_attempt_id.encode('utf-8')).hexdigest()[:32]}"


def stable_graph_attempt_id_for_practice_submission(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    question_id: str,
) -> str:
    raw = ":".join(
        [
            "practice",
            str(user_id or "").strip(),
            str(session_id or "").strip(),
            str(subject_id or "general").strip(),
            str(question_id or "").strip(),
        ]
    )
    return f"practice:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:32]}"
