from __future__ import annotations

from typing import Iterable

from loguru import logger

from app.domains.mastery.service import record_attempt
from app.services.rag.rag_service import RagContextResult, retrieve_context
from app.shared.schemas.contracts import (
    AnswerNormalizationResult,
    KnowledgeMasteryRecord,
    MasteryEvaluationResult,
    MasteryScoreBreakdown,
    PracticeRecommendation,
    RetrievalDiagnostics,
)
from app.knowledge.concept_registry import get_concept_registry

MCQ_OPTIONS = {"A", "B", "C", "D"}
REFERENCE_DOC_TYPES = ["question_bank", "exam_pattern", "chapter", "pdf", "url"]


def normalize_answer(*, selected_option: str, quiz_item: PracticeRecommendation) -> AnswerNormalizationResult:
    """Normalize the answer before scoring.

    V1 only accepts MCQ practice answers, but the contract leaves a clear branch
    point for blank / short-answer scoring later.
    """

    selected = str(selected_option or "").strip().upper()[:1]
    issues: list[str] = []
    if selected not in MCQ_OPTIONS:
        issues.append("selected_option_invalid")

    if quiz_item.correct_option not in MCQ_OPTIONS:
        issues.append("correct_option_invalid")

    if len(quiz_item.options or []) != 4:
        issues.append("mcq_options_incomplete")

    return AnswerNormalizationResult(
        answer_type="mcq",
        normalized_answer=selected,
        is_valid=not issues,
        issues=issues,
    )


def _empty_rag_result(*, question: str, issue: str = "") -> RagContextResult:
    diagnosis = RetrievalDiagnostics(
        query=question,
        hit_count=0,
        top_score=0.0,
        diagnosis="empty_knowledge_base",
        suggested_actions=["补充教材资料或题库解析后，掌握度判断会更稳。"],
    )
    return RagContextResult(
        docs=[],
        diagnosis=diagnosis,
        contextual_query=question,
        rag_ready=False,
        warning=issue,
    )


def _should_retry_retrieval(result: RagContextResult) -> bool:
    diagnosis = result.diagnosis
    return (
        not result.docs
        or not result.rag_ready
        or float(diagnosis.top_score or 0.0) < 0.45
        or diagnosis.diagnosis in {"empty_knowledge_base", "low_score", "no_matching_docs"}
    )


def retrieve_answer_references(
    *,
    user_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
) -> RagContextResult:
    query = "\n".join(
        part
        for part in [
            f"知识点：{quiz_item.knowledge_point or '综合'}",
            f"concept_id：{quiz_item.concept_id}" if quiz_item.concept_id else "",
            f"规范知识点：{quiz_item.concept_name}" if quiz_item.concept_name else "",
            f"题目：{quiz_item.question}",
            f"用户选择：{selected_option}",
            f"标准解析：{quiz_item.explanation}",
        ]
        if part.strip()
    )
    try:
        first = retrieve_context(
            question=query,
            subject_id=subject_id,
            user_id=user_id,
            top_k=4,
            min_score=0.45,
            doc_types=REFERENCE_DOC_TYPES,
        )
        if not _should_retry_retrieval(first):
            return first

        retry = retrieve_context(
            question=query,
            subject_id=subject_id,
            user_id=user_id,
            top_k=8,
            min_score=0.25,
            doc_types=REFERENCE_DOC_TYPES,
        )
        if retry.docs or retry.rag_ready:
            return retry
        return first
    except Exception as exc:
        logger.warning(f"⚠️ 掌握度评估 RAG 参考检索失败: {exc}")
        return _empty_rag_result(question=query, issue="rag_reference_failed")


def _weighted_score(*, accuracy: float, completeness: float, understanding_depth: float) -> float:
    score = accuracy * 0.55 + completeness * 0.20 + understanding_depth * 0.25
    return round(max(0.0, min(100.0, score)), 2)


def _score_dimensions(
    *,
    normalization: AnswerNormalizationResult,
    is_correct: bool,
    quiz_item: PracticeRecommendation,
    rag_result: RagContextResult,
) -> MasteryScoreBreakdown:
    issues = list(normalization.issues)
    has_explanation = bool(str(quiz_item.explanation or "").strip())
    has_rationales = len(quiz_item.option_rationales or {}) >= 4
    has_options = len(quiz_item.options or []) == 4
    doc_count = len(rag_result.docs)
    top_score = float(rag_result.diagnosis.top_score or 0.0)

    accuracy = 100.0 if is_correct else 0.0
    completeness = 100.0
    if not normalization.is_valid:
        completeness -= 40.0
    if not has_options:
        completeness -= 25.0
    if not has_explanation:
        completeness -= 20.0
    if not has_rationales:
        completeness -= 15.0
        issues.append("option_rationales_incomplete")
    completeness = max(0.0, completeness)

    understanding_depth = 85.0 if is_correct else 35.0
    if doc_count:
        understanding_depth += min(doc_count, 3) * 4
    if has_rationales:
        understanding_depth += 5
    understanding_depth = max(0.0, min(100.0, understanding_depth))

    confidence = 45.0
    if has_explanation:
        confidence += 15
    if has_rationales:
        confidence += 15
    if doc_count:
        confidence += min(20.0, top_score * 20)
    confidence = max(0.0, min(100.0, confidence))
    low_confidence = confidence < 60 or _should_retry_retrieval(rag_result)
    if low_confidence:
        issues.append("reference_confidence_low")

    return MasteryScoreBreakdown(
        accuracy=round(accuracy, 2),
        completeness=round(completeness, 2),
        understanding_depth=round(understanding_depth, 2),
        confidence=round(confidence, 2),
        rag_doc_count=doc_count,
        low_confidence=low_confidence,
        issues=issues,
    )


def _level_from_score(score: float) -> str:
    if score >= 80:
        return "mastered"
    if score >= 50:
        return "learning"
    return "weak"


def _selected_option_text(quiz_item: PracticeRecommendation, option_key: str) -> str:
    for option in quiz_item.options or []:
        if option.get("key") == option_key:
            return option.get("text", "")
    return ""


def _weak_points(
    *,
    knowledge_point: str,
    is_correct: bool,
    mastery_level: str,
    issues: Iterable[str],
) -> list[str]:
    weak = []
    if not is_correct or mastery_level == "weak":
        weak.append(knowledge_point)
    if "option_rationales_incomplete" in issues:
        weak.append(f"{knowledge_point}：选项辨析")
    return list(dict.fromkeys(item for item in weak if item))


def _build_feedback(
    *,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    is_correct: bool,
    mastery_level: str,
    score_breakdown: MasteryScoreBreakdown,
) -> str:
    knowledge_point = quiz_item.knowledge_point or "综合"
    selected_text = _selected_option_text(quiz_item, selected_option)
    selected_rationale = (quiz_item.option_rationales or {}).get(selected_option, "")
    correct_rationale = (quiz_item.option_rationales or {}).get(quiz_item.correct_option, "")

    if is_correct:
        return (
            f"这次「{knowledge_point}」判断是对的，准确性拉满。"
            f"当前掌握判断为 {mastery_level}，建议继续用 1-2 道变式题确认能否迁移。"
            f"{' 参考资料命中较少，后续补充教材解析会让判断更稳。' if score_breakdown.low_confidence else ''}"
        )

    selected_part = f"你选择了 {selected_option}"
    if selected_text:
        selected_part += f"（{selected_text}）"
    rationale_part = selected_rationale or "这一项容易和正确概念混淆，需要回到定义或条件边界重新核对。"
    correct_part = correct_rationale or quiz_item.explanation or "建议先看标准解析，再回到相关知识点复盘。"
    return (
        f"这次薄弱点定位在「{knowledge_point}」。{selected_part}，主要问题是：{rationale_part} "
        f"正确选项 {quiz_item.correct_option} 的关键依据是：{correct_part} "
        "建议下一步先复盘这个知识点的定义、适用条件和常见干扰项。"
    )


def _record_mastery_attempt(
    *,
    user_id: str,
    subject_id: str,
    knowledge_point: str,
    chapter_id: str,
    topic_id: str,
    concept_id: str,
    concept_name: str,
    is_correct: bool,
    fallback_score: float,
) -> tuple[float, str]:
    try:
        mastery = record_attempt(
            user_id=user_id,
            subject_id=subject_id,
            knowledge_point=knowledge_point,
            chapter_id=chapter_id,
            topic_id=topic_id,
            concept_id=concept_id,
            concept_name=concept_name,
            is_correct=is_correct,
        )
    except Exception as exc:
        logger.warning(f"⚠️ 知识点掌握度写入失败: {exc}")
        mastery = None

    if isinstance(mastery, KnowledgeMasteryRecord):
        return float(mastery.mastery_score or 0.0), mastery.mastery_level or _level_from_score(fallback_score)
    return fallback_score, _level_from_score(fallback_score)


def evaluate_practice_answer(
    *,
    user_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
) -> MasteryEvaluationResult:
    normalized_subject_id = subject_id or "general"
    concept_payload = _concept_payload_for_quiz_item(quiz_item, subject_id=normalized_subject_id)
    quiz_item = quiz_item.model_copy(update=concept_payload)
    knowledge_point = quiz_item.knowledge_point or quiz_item.concept_name or "综合"
    normalization = normalize_answer(selected_option=selected_option, quiz_item=quiz_item)
    is_correct = normalization.normalized_answer == quiz_item.correct_option
    rag_result = retrieve_answer_references(
        user_id=user_id,
        subject_id=normalized_subject_id,
        quiz_item=quiz_item,
        selected_option=normalization.normalized_answer,
    )
    score_breakdown = _score_dimensions(
        normalization=normalization,
        is_correct=is_correct,
        quiz_item=quiz_item,
        rag_result=rag_result,
    )
    score = _weighted_score(
        accuracy=score_breakdown.accuracy,
        completeness=score_breakdown.completeness,
        understanding_depth=score_breakdown.understanding_depth,
    )
    mastery_score, mastery_level = _record_mastery_attempt(
        user_id=user_id,
        subject_id=normalized_subject_id,
        knowledge_point=knowledge_point,
        chapter_id=quiz_item.chapter_id,
        topic_id=quiz_item.topic_id,
        concept_id=quiz_item.concept_id,
        concept_name=quiz_item.concept_name,
        is_correct=is_correct,
        fallback_score=score,
    )
    weak_points = _weak_points(
        knowledge_point=knowledge_point,
        is_correct=is_correct,
        mastery_level=mastery_level,
        issues=score_breakdown.issues,
    )
    feedback = _build_feedback(
        quiz_item=quiz_item,
        selected_option=normalization.normalized_answer,
        is_correct=is_correct,
        mastery_level=mastery_level,
        score_breakdown=score_breakdown,
    )
    return MasteryEvaluationResult(
        subject_id=normalized_subject_id,
        knowledge_point=knowledge_point,
        chapter_id=quiz_item.chapter_id,
        topic_id=quiz_item.topic_id,
        concept_id=quiz_item.concept_id,
        concept_name=quiz_item.concept_name,
        concept_mapping_status=quiz_item.concept_mapping_status,
        answer_type=normalization.answer_type,
        normalized_answer=normalization.normalized_answer,
        is_correct=is_correct,
        score=score,
        mastery_score=round(mastery_score, 2),
        mastery_level=mastery_level,
        weak_points=weak_points,
        feedback=feedback,
        score_breakdown=score_breakdown,
        retrieval_diagnosis=rag_result.diagnosis.diagnosis,
        reference_doc_count=len(rag_result.docs),
    )


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
