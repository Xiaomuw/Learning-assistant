from __future__ import annotations

from typing import Any

from app.domains.mastery.service import get_mastery
from app.domains.practice.common import determine_difficulty, infer_topic_from_question, normalize_quiz_item
from app.domains.practice.generation import PracticeGenerationResult, build_mixed_practice_items_with_status
from app.shared.schemas.contracts import (
    PracticeRecommendation,
    QuizGenerationContext,
    QuizPlan,
    QuizQualityReport,
    RetrievedDocument,
)

OPTION_KEYS = ("A", "B", "C", "D")
VALID_DIFFICULTIES = {"基础", "变式", "易错"}


def _unique_non_empty(values: list[Any], *, limit: int = 6) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text[:60])
        if len(result) >= limit:
            break
    return result


def build_quiz_plan_from_state(state: dict[str, Any]) -> QuizPlan:
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    explanation = state.get("explanation") if isinstance(state.get("explanation"), dict) else {}
    question = str(state.get("question", "") or "")
    subject_id = str(state.get("subject_id", "general") or "general")
    subject_name = str(state.get("subject_name", "综合") or "综合")
    user_id = str(state.get("user_id", "") or "")
    error_count = dict(memory.get("error_count", {}) or {})

    mastery_snapshot: list[dict[str, Any]] = []
    if user_id:
        try:
            mastery_snapshot = [
                item.model_dump()
                for item in get_mastery(user_id=user_id, subject_id=subject_id, limit=20).items
            ]
        except Exception:
            mastery_snapshot = []

    weak_mastery = sorted(
        (
            item
            for item in mastery_snapshot
            if str(item.get("mastery_level", "") or "") in {"weak", "learning"}
        ),
        key=lambda item: (
            0 if str(item.get("mastery_level", "") or "") == "weak" else 1,
            float(item.get("mastery_score", 0) or 0),
        ),
    )
    inferred_topic = str(explanation.get("topic") or "").strip() or infer_topic_from_question(question, subject_name)
    focus_points = _unique_non_empty(
        [
            *[item.get("knowledge_point") for item in weak_mastery],
            *list(memory.get("weak_points", []) or []),
            inferred_topic,
            *list(memory.get("recent_topics", []) or []),
        ],
        limit=5,
    )
    primary_topic = focus_points[0] if focus_points else inferred_topic
    difficulty = determine_difficulty(primary_topic, error_count)
    for item in weak_mastery:
        if item.get("knowledge_point") != primary_topic:
            continue
        wrong_count = int(item.get("wrong_count", 0) or 0)
        if wrong_count >= 4:
            difficulty = "易错"
        elif wrong_count >= 2 and difficulty == "基础":
            difficulty = "变式"
        break

    source = "mastery" if weak_mastery else "memory" if memory.get("weak_points") else "question"
    return QuizPlan(
        focus_points=focus_points or [primary_topic],
        target_difficulty=difficulty,
        mastery_snapshot=mastery_snapshot[:10],
        source=source,
    )


def extract_quiz_knowledge_points(state: dict[str, Any], plan: QuizPlan) -> list[str]:
    explanation = state.get("explanation") if isinstance(state.get("explanation"), dict) else {}
    subject_name = str(state.get("subject_name", "综合") or "综合")
    question = str(state.get("question", "") or "")
    inferred_topic = infer_topic_from_question(question, subject_name)
    return _unique_non_empty(
        [
            *plan.focus_points,
            explanation.get("topic"),
            inferred_topic,
            subject_name if subject_name != "通用知识" else "",
        ],
        limit=6,
    )


def build_quiz_generation_context(
    *,
    state: dict[str, Any],
    plan: QuizPlan,
    focus_points: list[str],
    rag_docs: list[RetrievedDocument],
    requested_count: int,
) -> QuizGenerationContext:
    subject_id = str(state.get("subject_id", "general") or "general")
    subject_name = str(state.get("subject_name", "综合") or "综合")
    topic = focus_points[0] if focus_points else (plan.focus_points[0] if plan.focus_points else subject_name)
    mastery_summary = _format_mastery_summary(plan.mastery_snapshot, focus_points)
    rag_context = _format_rag_context(rag_docs)
    retry_count = int(state.get("quiz_retry_count", 0) or 0)
    return QuizGenerationContext(
        subject_id=subject_id,
        subject_name=subject_name,
        topic=topic,
        difficulty=plan.target_difficulty,
        focus_points=focus_points or [topic],
        rag_context=rag_context,
        mastery_summary=mastery_summary,
        retry_count=retry_count,
        requested_count=requested_count,
    )


def generate_quiz_items_from_context(
    *,
    state: dict[str, Any],
    context: QuizGenerationContext,
) -> PracticeGenerationResult:
    return build_mixed_practice_items_with_status(
        subject_id=context.subject_id,
        subject_name=context.subject_name,
        topic=context.topic,
        difficulty=context.difficulty,
        count=context.requested_count,
        original_question=str(state.get("question", "") or ""),
        user_style_name=str(state.get("user_style_name", "") or ""),
        user_style_prompt=str(state.get("user_style_prompt", "") or ""),
        short_term_context=str(state.get("short_term_context", "") or "（暂无短期上下文）"),
        session_memory_context=str(state.get("session_memory_context", "") or "（暂无会话摘要）"),
        long_term_context=str(state.get("long_term_context", "") or "（暂无长期学习记忆）"),
        model_name=str(state.get("model_name", "") or "").strip() or None,
        rag_context=context.rag_context or "（本轮未检索到额外知识库材料）",
        knowledge_points=context.focus_points,
    )


def evaluate_quiz_quality(
    *,
    items: list[PracticeRecommendation | dict[str, Any]],
    context: QuizGenerationContext,
) -> QuizQualityReport:
    normalized = [normalize_quiz_item(item.model_dump() if isinstance(item, PracticeRecommendation) else item) for item in items]
    issues: list[str] = []
    if len(normalized) < context.requested_count:
        issues.append(f"题目数量不足: expected={context.requested_count}, actual={len(normalized)}")

    focus_points = [point.lower() for point in context.focus_points if point.strip()]
    for index, item in enumerate(normalized, start=1):
        option_keys = [str(option.get("key", "") or "").upper() for option in item.options]
        option_texts = [str(option.get("text", "") or "").strip() for option in item.options]
        if option_keys != list(OPTION_KEYS) or len(option_texts) != 4 or any(not text for text in option_texts):
            issues.append(f"第 {index} 题选项不是完整 A/B/C/D")
        if item.correct_option not in OPTION_KEYS:
            issues.append(f"第 {index} 题正确选项无效")
        if len(item.explanation.strip()) < 8:
            issues.append(f"第 {index} 题缺少标准解析")
        missing_rationales = [key for key in OPTION_KEYS if not item.option_rationales.get(key, "").strip()]
        if missing_rationales:
            issues.append(f"第 {index} 题缺少选项解析: {','.join(missing_rationales)}")
        if not item.knowledge_point.strip():
            issues.append(f"第 {index} 题缺少知识点")
        if item.difficulty not in VALID_DIFFICULTIES:
            issues.append(f"第 {index} 题难度无效")
        elif item.difficulty != context.difficulty:
            issues.append(f"第 {index} 题难度不匹配: expected={context.difficulty}, actual={item.difficulty}")
        if focus_points and not _is_item_related_to_focus(item, focus_points):
            issues.append(f"第 {index} 题与目标知识点相关性不足")

    passed = not issues
    return QuizQualityReport(
        passed=passed,
        issues=issues,
        checked_count=len(normalized),
        expected_count=context.requested_count,
        retry_recommended=not passed,
    )


def build_quiz_final_answer(
    *,
    context: QuizGenerationContext,
    status: dict[str, Any],
    report: QuizQualityReport,
) -> str:
    generated_count = int(status.get("generated_count") or 0)
    fallback_count = int(status.get("fallback_count") or 0)
    partial = bool(status.get("partial", False))
    answer = (
        f"我已经围绕「{context.topic}」准备了 {generated_count} 道{context.difficulty}单选题，"
        "你可以直接去刷题页继续做。"
    )
    if fallback_count or partial:
        answer += f" 其中 {fallback_count} 道使用备用题补齐。"
    if not report.passed:
        answer += " 本轮已触发质量检查降级，建议做题后重点查看解析。"
    degraded_reason = str(status.get("degraded_reason", "") or "").strip()
    if partial and degraded_reason:
        answer += f" 降级原因：{degraded_reason}"
    return answer


def _format_mastery_summary(snapshot: list[dict[str, Any]], focus_points: list[str]) -> str:
    if not snapshot:
        return "暂无精细掌握度记录，按当前问题和长期记忆出题。"
    focus = set(focus_points)
    lines: list[str] = []
    for item in snapshot[:8]:
        point = str(item.get("knowledge_point", "") or "")
        if focus and point not in focus:
            continue
        lines.append(
            f"{point}: level={item.get('mastery_level', 'weak')}, "
            f"score={item.get('mastery_score', 0)}, "
            f"attempt={item.get('attempt_count', 0)}, wrong={item.get('wrong_count', 0)}"
        )
    return "\n".join(lines) if lines else "掌握度记录存在，但与本轮知识点匹配较少。"


def _format_rag_context(docs: list[RetrievedDocument]) -> str:
    if not docs:
        return "（本轮未检索到额外知识库材料）"
    chunks: list[str] = []
    for index, doc in enumerate(docs[:5], start=1):
        doc_type = str(doc.metadata.get("doc_type", "document") or "document")
        source = str(doc.metadata.get("source", "") or "").strip()
        content = " ".join(doc.content.split())[:700]
        chunks.append(f"[{index}] type={doc_type} score={doc.score:.2f} source={source}\n{content}")
    return "\n\n".join(chunks)


def _is_item_related_to_focus(item: PracticeRecommendation, focus_points: list[str]) -> bool:
    haystack = " ".join(
        [
            item.knowledge_point,
            item.question,
            item.explanation,
        ]
    ).lower()
    for focus in focus_points:
        if focus and (focus in haystack or item.knowledge_point.lower() in focus):
            return True
    return False
