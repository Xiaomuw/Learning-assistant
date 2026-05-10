from __future__ import annotations

import hashlib
from typing import Any, Callable

from app.domains.memory.session_summary import normalize_session_memory
from app.domains.mastery.evaluation import evaluate_practice_answer
from app.domains.practice.common import OPTION_KEYS, MAX_RECENT_TOPICS, normalize_practice_source_type, utc_iso
from app.infrastructure.db.repositories.practice import (
    create_practice_attempt_record,
    find_practice_attempt_record_for_question,
)
from app.infrastructure.db.repositories.sessions import (
    get_chat_session_record,
    update_chat_session_memory_record,
)
from app.infrastructure.db.repositories.users import get_user_memory_record, save_user_memory_record
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


def _find_existing_practice_attempt(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    question_id: str,
) -> dict[str, Any] | None:
    record = find_practice_attempt_record_for_question(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        question_id=question_id,
    )
    return record.model_dump() if record else None


def record_practice_attempt_and_update_memory(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    graph_mastery_update: Callable[..., None] | None = None,
) -> PracticeSubmissionResult:
    selected = _normalize_selected_option(selected_option)
    normalized_item = _normalize_submission_quiz_item(PracticeRecommendation.model_validate(quiz_item))
    concept_payload = _concept_payload_for_quiz_item(normalized_item, subject_id=subject_id)
    normalized_item = _normalize_submission_quiz_item(normalized_item.model_copy(update=concept_payload))
    correct_option = normalized_item.correct_option
    knowledge_point = normalized_item.concept_name or normalized_item.knowledge_point or "综合"

    existing_attempt = _find_existing_practice_attempt(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id or "general",
        question_id=str(normalized_item.question_id or ""),
    )
    if existing_attempt is not None:
        existing_item = _quiz_item_from_existing_attempt(
            existing_attempt,
            fallback=normalized_item,
        )
        existing_selected = _normalize_selected_option(existing_attempt.get("selected_option") or selected)
        memory = UserMemoryRecord.model_validate(_get_user_memory(user_id))
        return PracticeSubmissionResult(
            is_correct=bool(existing_attempt.get("is_correct")),
            selected_option=existing_selected,
            correct_option=existing_item.correct_option,
            explanation=existing_item.explanation,
            option_rationales=existing_item.option_rationales,
            memory=memory,
            session_memory=None,
            mastery_evaluation=None,
            personalized_feedback="这次提交已记录过，页面会继续展示首次判题结果。",
            duplicate_submission=True,
        )

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
    if graph_mastery_update is not None:
        graph_mastery_update(
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


def _normalize_selected_option(value: Any) -> str:
    selected = str(value or "").strip().upper()[:1]
    if selected not in OPTION_KEYS:
        raise ValueError("selected_option 必须是 A/B/C/D")
    return selected


def _normalize_submission_quiz_item(item: PracticeRecommendation) -> PracticeRecommendation:
    question = str(item.question or "").strip()
    if not question:
        raise ValueError("quiz_item.question 不能为空")

    option_map: dict[str, str] = {}
    for option in item.options or []:
        key = str(option.get("key") or "").strip().upper()[:1]
        text = str(option.get("text") or "").strip()
        if key in OPTION_KEYS and text:
            option_map[key] = text

    if set(option_map) != set(OPTION_KEYS):
        raise ValueError("quiz_item.options 必须完整包含 A/B/C/D 四个选项")

    correct_option = str(item.correct_option or "").strip().upper()[:1]
    if correct_option not in OPTION_KEYS:
        raise ValueError("quiz_item.correct_option 必须是 A/B/C/D")

    explanation = str(item.explanation or "").strip()
    if not explanation:
        explanation = f"正确答案是 {correct_option}。请结合题干条件和选项辨析复盘。"

    raw_rationales = {
        str(key).strip().upper()[:1]: str(value or "").strip()
        for key, value in dict(item.option_rationales or {}).items()
    }
    rationales: dict[str, str] = {}
    for key in OPTION_KEYS:
        rationale = raw_rationales.get(key, "")
        if not rationale:
            rationale = (
                f"{key} 是正确答案，依据见标准解析。"
                if key == correct_option
                else "该选项不是本题正确答案，需要对照题干条件和标准解析排除。"
            )
        rationales[key] = rationale

    return item.model_copy(
        update={
            "question_id": str(item.question_id or "").strip()
            or _fallback_question_id(question=question, option_map=option_map, correct_option=correct_option),
            "question": question,
            "options": [{"key": key, "text": option_map[key]} for key in OPTION_KEYS],
            "correct_option": correct_option,
            "explanation": explanation,
            "option_rationales": rationales,
        }
    )


def _fallback_question_id(
    *,
    question: str,
    option_map: dict[str, str],
    correct_option: str,
) -> str:
    identity = "|".join(
        [
            question,
            *[f"{key}:{option_map.get(key, '')}" for key in OPTION_KEYS],
            correct_option,
        ]
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:32]
    return f"practice:{digest}"


def _quiz_item_from_existing_attempt(
    existing_attempt: dict[str, Any],
    *,
    fallback: PracticeRecommendation,
) -> PracticeRecommendation:
    snapshot = existing_attempt.get("question_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        try:
            return _normalize_submission_quiz_item(PracticeRecommendation.model_validate(snapshot))
        except Exception:
            pass
    return fallback


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
