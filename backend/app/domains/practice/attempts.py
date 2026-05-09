from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.memory.session_summary import normalize_session_memory
from app.domains.mastery.evaluation import evaluate_practice_answer
from app.domains.practice.common import MAX_RECENT_TOPICS, normalize_practice_source_type, utc_iso
from app.infrastructure.db.repositories.practice import create_practice_attempt_record
from app.infrastructure.db.repositories.sessions import (
    get_chat_session_record,
    update_chat_session_memory_record,
)
from app.infrastructure.db.repositories.users import get_user_memory_record, save_user_memory_record
from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph
from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
from app.shared.schemas.contracts import PracticeRecommendation, PracticeSubmissionResult, UserMemoryRecord
from app.knowledge.concept_registry import get_concept_registry


def _get_user_memory(user_id: str) -> dict[str, Any]:
    return get_user_memory_record(user_id).model_dump()


def _save_user_memory(user_id: str, memory: dict[str, Any]) -> dict[str, Any]:
    payload = UserMemoryRecord.model_validate(memory)
    return save_user_memory_record(user_id, payload).model_dump()


def _get_chat_session(user_id: str, session_id: str) -> dict[str, Any] | None:
    record = get_chat_session_record(user_id, session_id)
    return record.model_dump() if record else None


def _update_chat_session_memory(user_id: str, session_id: str, session_memory: dict[str, Any]) -> dict[str, Any] | None:
    record = update_chat_session_memory_record(user_id, session_id, session_memory)
    return record.model_dump() if record else None


def _create_practice_attempt(**kwargs: Any) -> dict[str, Any]:
    return create_practice_attempt_record(**kwargs).model_dump()


def record_practice_attempt_and_update_memory(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
) -> PracticeSubmissionResult:
    normalized_item = PracticeRecommendation.model_validate(quiz_item)
    concept_payload = _concept_payload_for_quiz_item(normalized_item, subject_id=subject_id)
    normalized_item = normalized_item.model_copy(update=concept_payload)
    selected = selected_option.strip().upper()[:1]
    correct_option = normalized_item.correct_option
    knowledge_point = normalized_item.concept_name or normalized_item.knowledge_point or "综合"
    mastery_evaluation = evaluate_practice_answer(
        user_id=user_id,
        subject_id=subject_id or "general",
        quiz_item=normalized_item,
        selected_option=selected,
    )
    is_correct = mastery_evaluation.is_correct

    legacy_attempt = _create_practice_attempt(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id or "general",
        question_id=str(normalized_item.question_id),
        question_snapshot=normalized_item.model_dump(),
        selected_option=selected,
        is_correct=is_correct,
        knowledge_point=knowledge_point,
        chapter_id=normalized_item.chapter_id,
        topic_id=normalized_item.topic_id,
        concept_id=normalized_item.concept_id,
        concept_name=normalized_item.concept_name,
        concept_mapping_status=normalized_item.concept_mapping_status,
        source_type=normalize_practice_source_type(normalized_item.source_type),
    )
    _update_graph_mastery_from_practice_attempt(
        legacy_attempt=legacy_attempt,
        user_id=user_id,
        subject_id=subject_id or "general",
        quiz_item=normalized_item,
        selected_option=selected,
        is_correct=is_correct,
    )

    memory = _get_user_memory(user_id)
    weak_points = list(memory.get("weak_points", []) or [])
    error_count = dict(memory.get("error_count", {}) or {})
    recent_topics = [knowledge_point, *list(memory.get("recent_topics", []) or [])]
    deduped_topics: list[str] = []
    for topic in recent_topics:
        if topic and topic not in deduped_topics:
            deduped_topics.append(topic)
    deduped_topics = deduped_topics[:MAX_RECENT_TOPICS]

    if not is_correct:
        error_count[knowledge_point] = int(error_count.get(knowledge_point, 0)) + 1
        if knowledge_point not in weak_points:
            weak_points.append(knowledge_point)

    updated_memory = _save_user_memory(
        user_id,
        {
            "weak_points": weak_points,
            "error_count": error_count,
            "recent_topics": deduped_topics,
            "last_session": f"{session_id}@{utc_iso()}" if session_id else memory.get("last_session", ""),
        },
    )

    next_session_memory = None
    if session_id:
        existing_session = _get_chat_session(user_id, session_id)
        if existing_session:
            session_memory = normalize_session_memory(existing_session.get("session_memory"))
            resolved_points = list(session_memory.get("resolved_points", []) or [])
            open_loops = list(session_memory.get("open_loops", []) or [])
            summary_text = str(session_memory.get("summary_text", "") or "")
            if is_correct:
                resolved_note = f"已完成围绕「{knowledge_point}」的选择题练习"
                if resolved_note not in resolved_points:
                    resolved_points.insert(0, resolved_note)
                open_loops = [
                    item for item in open_loops
                    if knowledge_point not in str(item)
                ]
                summary_text = summary_text or f"当前会话已完成一轮「{knowledge_point}」选择题练习。"
            else:
                retry_note = f"继续复盘「{knowledge_point}」选择题中的易错点"
                if retry_note not in open_loops:
                    open_loops.insert(0, retry_note)
                summary_text = f"当前会话正在围绕「{knowledge_point}」通过选择题查漏补缺。"

            next_session_memory = {
                **session_memory,
                "active_topic": knowledge_point,
                "current_goal": f"通过选择题巩固「{knowledge_point}」",
                "summary_text": summary_text[:400],
                "open_loops": open_loops[:5],
                "resolved_points": resolved_points[:5],
                "last_question_type": "practice",
                "last_updated_at": utc_iso(),
            }
            _update_chat_session_memory(
                user_id=user_id,
                session_id=session_id,
                session_memory=next_session_memory,
            )

    return PracticeSubmissionResult(
        is_correct=is_correct,
        selected_option=selected,
        correct_option=correct_option,
        explanation=normalized_item.explanation,
        option_rationales=normalized_item.option_rationales,
        memory=UserMemoryRecord.model_validate(updated_memory),
        session_memory=next_session_memory,
        mastery_evaluation=mastery_evaluation,
        personalized_feedback=mastery_evaluation.feedback,
    )


def _update_graph_mastery_from_practice_attempt(
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

    graph_attempt_id = _graph_attempt_id_for_practice_attempt(legacy_attempt_id)
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
        build_mastery_graph(
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
        logger.warning("Graph-era mastery update failed open for practice attempt {}: {}", legacy_attempt_id, exc.__class__.__name__)


def _value_from_record(record: Any, key: str) -> str:
    if isinstance(record, dict):
        value = record.get(key)
    else:
        value = getattr(record, key, "")
    return str(value or "").strip()


def _graph_attempt_id_for_practice_attempt(legacy_attempt_id: str) -> str:
    graph_attempt_id = f"practice:{legacy_attempt_id}"
    if len(graph_attempt_id) <= 100:
        return graph_attempt_id
    import hashlib

    return f"practice:{hashlib.sha1(legacy_attempt_id.encode('utf-8')).hexdigest()[:32]}"


def _concept_payload_for_quiz_item(item: PracticeRecommendation, *, subject_id: str) -> dict[str, str]:
    registry = get_concept_registry()
    if item.concept_id:
        concept = registry.get_concept(item.concept_id)
        if concept is not None:
            return {
                "chapter_id": concept.chapter_id,
                "topic_id": concept.topic_id,
                "concept_id": concept.concept_id,
                "concept_name": concept.concept_name,
                "concept_mapping_status": "matched",
            }
    match = registry.match_query(
        "\n".join(
            part
            for part in [item.knowledge_point, item.concept_name, item.question, item.explanation]
            if str(part or "").strip()
        ),
        subject_id=subject_id,
    )
    if match.status == "matched" and match.concept_id:
        concept = registry.get_concept(match.concept_id)
        if concept is not None:
            return {
                "chapter_id": concept.chapter_id,
                "topic_id": concept.topic_id,
                "concept_id": concept.concept_id,
                "concept_name": concept.concept_name,
                "concept_mapping_status": "matched",
            }
    return {
        "chapter_id": item.chapter_id,
        "topic_id": item.topic_id,
        "concept_id": item.concept_id,
        "concept_name": item.concept_name or item.knowledge_point,
        "concept_mapping_status": item.concept_mapping_status or match.status,
    }
