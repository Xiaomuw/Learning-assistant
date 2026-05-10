from __future__ import annotations

from app.application.practice.graph_facts import (
    maybe_dual_write_practice_attempt,
    update_graph_mastery_from_practice_attempt,
)
from app.domains.memory.service import build_request_context
from app.domains.practice.service import (
    build_recommended_practice_items,
    record_practice_attempt_and_update_memory,
)
from app.domains.practice.llm import resolve_practice_generation_model
from app.infrastructure.db.repositories.subjects import get_subject_record
from app.shared.schemas.contracts import PracticeRecommendation, PracticeRecommendationsResult, PracticeSubmissionResult
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


def get_recommendations(*, user_id: str, subject_id: str | None, limit: int) -> PracticeRecommendationsResult:
    context = build_request_context(user_id, "")
    normalized_subject_id = normalize_subject_id(subject_id)
    subject = get_subject_record(normalized_subject_id)
    subject_name = subject.name if subject else str(DEFAULT_SUBJECTS[0]["name"])
    items = build_recommended_practice_items(
        user_id=user_id,
        subject_id=normalized_subject_id,
        subject_name=subject_name,
        user_style_name="",
        user_style_prompt="",
        short_term_context=context["short_term_context"],
        session_memory_context=context["session_memory_context"],
        long_term_context=context["long_term_context"],
        limit=limit,
        model_name=resolve_practice_generation_model(),
    )
    return PracticeRecommendationsResult(
        subject_id=normalized_subject_id,
        items=[PracticeRecommendation.model_validate(item) for item in items],
    )


def submit_attempt(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
) -> PracticeSubmissionResult:
    subject_id = normalize_subject_id(subject_id)
    result = record_practice_attempt_and_update_memory(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        quiz_item=quiz_item,
        selected_option=selected_option,
        graph_mastery_update=update_graph_mastery_from_practice_attempt,
    )
    enriched_quiz_item = quiz_item
    if result.mastery_evaluation and result.mastery_evaluation.concept_id:
        enriched_quiz_item = quiz_item.model_copy(
            update={
                "chapter_id": result.mastery_evaluation.chapter_id,
                "topic_id": result.mastery_evaluation.topic_id,
                "concept_id": result.mastery_evaluation.concept_id,
                "concept_name": result.mastery_evaluation.concept_name,
                "concept_mapping_status": result.mastery_evaluation.concept_mapping_status,
            }
        )
    maybe_dual_write_practice_attempt(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        quiz_item=enriched_quiz_item,
        selected_option=selected_option,
        result=result,
    )
    return result
