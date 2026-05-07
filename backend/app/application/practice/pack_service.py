from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.domains.practice.quiz_request import (
    build_quiz_clarification_panel,
    context_from_practice_question,
    resolve_quiz_request,
)
from app.orchestration.graphs.question_generation.adapter import LegacyPracticeQuestionCandidateGenerator
from app.orchestration.graphs.question_generation.graph import build_production_graph
from app.services.runtime_models import resolve_active_chat_model
from app.shared.schemas.agent_graphs import SourcePolicy
from app.shared.schemas.contracts import PracticePackResult, PracticeRecommendation
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


class PracticePackService:
    def create_pack_from_request(
        self,
        *,
        user_id: str,
        session_id: str,
        subject_id: str,
        request_text: str,
        current_practice_question: dict[str, Any] | PracticeRecommendation | None = None,
        last_practice_pack: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> PracticePackResult:
        subject_id = normalize_subject_id(subject_id)
        resolver_context = context_from_practice_question(
            current_practice_question=current_practice_question,
            last_practice_pack=last_practice_pack,
            extra=context,
        )
        resolution = resolve_quiz_request(request_text, resolver_context)
        if resolution.need_clarification:
            return PracticePackResult(
                subject_id=subject_id,
                quiz_request=resolution,
                quiz_clarification=build_quiz_clarification_panel(resolution),
                items=[],
                generation_status={"needs_clarification": True},
                message="还需要先确认练习方向。",
            )
        if resolution.action != "generate_practice_pack" or not resolution.topic:
            fallback_resolution = resolve_quiz_request("帮我出题", {})
            return PracticePackResult(
                subject_id=subject_id,
                quiz_request=fallback_resolution,
                quiz_clarification=build_quiz_clarification_panel(fallback_resolution),
                items=[],
                generation_status={"needs_clarification": True},
                message="还需要先确认练习方向。",
            )

        resolved_from_request = bool(resolution.subject_id)
        subject_id = normalize_subject_id(resolution.subject_id or subject_id)
        subject_name = (
            _subject_name(subject_id)
            if resolved_from_request
            else str((context or {}).get("subject_name") or _subject_name(subject_id))
        )
        generator = LegacyPracticeQuestionCandidateGenerator(
            user_id=user_id,
            subject_id=subject_id,
            subject_name=subject_name,
            original_question=request_text,
            model_name=resolve_active_chat_model(),
        )
        result = build_production_graph(candidate_generator=generator).compile().invoke(
            {
                "run_id": f"practice-pack-{uuid4()}",
                "user_id": user_id,
                "thread_id": session_id,
                "notebook_id": subject_id,
                "graph_type": "question_generation",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "user_message": request_text,
                "quiz_request": resolution.model_dump(mode="json"),
                "concepts": [
                    {
                        "concept_id": resolution.topic.lower().replace(" ", "-")[:64],
                        "name": resolution.topic,
                    }
                ],
                "count": int(resolution.count or 5),
                "requested_count": int(resolution.count or 5),
                "difficulty": _difficulty_label(resolution.difficulty),
            }
        )
        generation_status = dict(result.get("generation_status") or {})
        errors = [dict(item) for item in list(result.get("errors") or []) if isinstance(item, dict)]
        items = [
            _practice_recommendation_from_question_item(item)
            for item in list(result.get("question_items") or [])
        ]
        return PracticePackResult(
            subject_id=subject_id,
            quiz_request=resolution,
            items=items,
            generation_status=generation_status,
            errors=errors,
            message=_pack_message(items=items, generation_status=generation_status, errors=errors),
        )


def create_pack_from_request(**kwargs: Any) -> PracticePackResult:
    return PracticePackService().create_pack_from_request(**kwargs)


def _practice_recommendation_from_question_item(raw_item: dict[str, Any]) -> PracticeRecommendation:
    answer_key = raw_item.get("answer_key") if isinstance(raw_item.get("answer_key"), dict) else {}
    return PracticeRecommendation(
        question_id=str(raw_item.get("id") or uuid4()),
        question=str(raw_item.get("stem") or ""),
        options=[
            {"key": str(option.get("key") or ""), "text": str(option.get("text") or "")}
            for option in list(raw_item.get("options") or [])
            if isinstance(option, dict)
        ],
        correct_option=str(answer_key.get("correct_option") or "A"),
        explanation=str(answer_key.get("explanation") or ""),
        option_rationales=dict(answer_key.get("option_rationales") or {}),
        knowledge_point=str(raw_item.get("primary_concept_id") or ""),
        difficulty=str(raw_item.get("difficulty") or "基础"),
        source_type="ai_generated",
        source_name="PracticePackService",
        hint=str((raw_item.get("rubric") or {}).get("full_credit") or "") if isinstance(raw_item.get("rubric"), dict) else "",
    )


def _difficulty_label(value: str) -> str:
    return {
        "easy": "基础",
        "medium": "变式",
        "hard": "易错",
        "adaptive": "基础",
        "unknown": "基础",
    }.get(str(value or "adaptive"), "基础")


def _subject_name(subject_id: str) -> str:
    for subject in DEFAULT_SUBJECTS:
        if subject["id"] == subject_id:
            return str(subject["name"])
    return str(DEFAULT_SUBJECTS[0]["name"])


def _pack_message(
    *,
    items: list[PracticeRecommendation],
    generation_status: dict[str, Any],
    errors: list[dict[str, Any]],
) -> str:
    if items:
        if generation_status.get("ai_generation_failed") or generation_status.get("fallback_count"):
            return "已生成练习题；部分题目使用了备用生成策略。"
        return "已生成新的练习题。"
    if generation_status.get("empty_generation") or errors:
        reason = str(generation_status.get("degraded_reason") or "").strip()
        if reason:
            return f"已识别练习方向，但题目生成失败：{reason}"
        return "已识别练习方向，但题目生成失败，请稍后重试。"
    return ""
