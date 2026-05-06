"""
出题专项 LangGraph 节点
======================
把“读掌握度 → 知识点 → RAG → 上下文 → 生成 → 质检 → 输出”显式拆成图节点。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.practice.service import (
    build_quiz_final_answer,
    build_quiz_generation_context,
    build_quiz_plan_from_state,
    evaluate_quiz_quality,
    extract_quiz_knowledge_points,
    generate_quiz_items_from_context,
)
from app.services.rag.rag_service import retrieve_context
from app.shared.schemas.contracts import (
    PracticeRecommendation,
    QuizGenerationContext,
    QuizPlan,
    QuizQualityReport,
    RetrievedDocument,
)
from app.shared.schemas.state import AgentState

QUIZ_COUNT = 2
QUIZ_MAX_RETRY = 1


def _quiz_item_payload(item: PracticeRecommendation | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, PracticeRecommendation):
        return item.model_dump()
    return dict(item)


def quiz_mastery_agent(state: AgentState) -> dict[str, Any]:
    plan = build_quiz_plan_from_state(dict(state))
    logger.info(
        f"✏️ quiz_mastery_node | focus={plan.focus_points} | "
        f"difficulty={plan.target_difficulty} | source={plan.source}"
    )
    return {
        "quiz_plan": plan.model_dump(),
        "quiz_focus_points": plan.focus_points,
        "quiz_target_difficulty": plan.target_difficulty,
        "quiz_retry_count": int(state.get("quiz_retry_count", 0) or 0),
    }


def quiz_knowledge_agent(state: AgentState) -> dict[str, Any]:
    plan = QuizPlan.model_validate(state.get("quiz_plan") or {})
    focus_points = extract_quiz_knowledge_points(dict(state), plan)
    plan = plan.model_copy(update={"focus_points": focus_points})
    return {
        "quiz_plan": plan.model_dump(),
        "quiz_focus_points": focus_points,
        "quiz_target_difficulty": plan.target_difficulty,
    }


def quiz_rag_agent(state: AgentState) -> dict[str, Any]:
    focus_points = list(state.get("quiz_focus_points") or [])
    subject_name = str(state.get("subject_name", "") or "")
    retry_count = int(state.get("quiz_retry_count", 0) or 0)
    query_parts = [subject_name, *focus_points, "常考题型", "易错点", "出题"]
    if retry_count:
        query_parts.extend(["扩展检索", "章节", "题库解析"])
    query = " ".join(part for part in query_parts if str(part).strip())
    if not query.strip():
        query = str(state.get("question", "") or "综合练习")

    try:
        rag_result = retrieve_context(
            question=query,
            subject_id=state.get("subject_id"),
            user_id=state.get("user_id"),
            memory=state.get("memory") if isinstance(state.get("memory"), dict) else {},
            short_term_messages=list(state.get("short_term_messages") or []),
            session_memory=state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {},
            top_k=8 if retry_count else 5,
            min_score=0.35 if retry_count else 0.45,
            doc_types=["exam_pattern", "question_bank", "chapter", "pdf", "url"],
        )
        docs = [doc.model_dump() for doc in rag_result.docs]
        diagnosis = rag_result.diagnosis.model_dump()
        logger.info(
            f"✏️ quiz_rag_node | hits={len(docs)} | "
            f"diagnosis={diagnosis.get('diagnosis')} | retry={retry_count}"
        )
        return {
            "quiz_rag_docs": docs,
            "quiz_rag_diagnosis": diagnosis,
        }
    except Exception as exc:
        return {
            "quiz_rag_docs": [],
            "quiz_rag_diagnosis": {"diagnosis": "rag_error", "error_type": type(exc).__name__},
            "graph_warnings": [f"quiz_rag_node failed with {type(exc).__name__}; quiz generation continued."],
        }


def quiz_context_agent(state: AgentState) -> dict[str, Any]:
    plan = QuizPlan.model_validate(state.get("quiz_plan") or {})
    focus_points = list(state.get("quiz_focus_points") or plan.focus_points)
    docs = [
        RetrievedDocument.model_validate(item)
        for item in list(state.get("quiz_rag_docs") or [])
        if isinstance(item, dict)
    ]
    context = build_quiz_generation_context(
        state=dict(state),
        plan=plan,
        focus_points=focus_points,
        rag_docs=docs,
        requested_count=QUIZ_COUNT,
    )
    return {"quiz_context": context.model_dump()}


def quiz_generate_agent(state: AgentState) -> dict[str, Any]:
    context = QuizGenerationContext.model_validate(state.get("quiz_context") or {})
    generation_result = generate_quiz_items_from_context(state=dict(state), context=context)
    quiz_payloads = [_quiz_item_payload(item) for item in generation_result.items]
    status = {
        **generation_result.status,
        "retry_count": context.retry_count,
        "focus_points": context.focus_points,
        "rag_doc_count": len(state.get("quiz_rag_docs") or []),
    }
    return {
        "quiz_items": quiz_payloads,
        "quiz_generation_status": status,
    }


def quiz_quality_agent(state: AgentState) -> dict[str, Any]:
    context = QuizGenerationContext.model_validate(state.get("quiz_context") or {})
    report = evaluate_quiz_quality(items=list(state.get("quiz_items") or []), context=context)
    status = dict(state.get("quiz_generation_status") or {})
    status.update(
        {
            "quality_passed": report.passed,
            "quality_issues": report.issues,
            "retry_count": int(state.get("quiz_retry_count", 0) or 0),
            "focus_points": context.focus_points,
            "rag_doc_count": len(state.get("quiz_rag_docs") or []),
        }
    )
    if not report.passed:
        status["partial"] = True
        if not status.get("degraded_reason"):
            status["degraded_reason"] = "题目质量检查未完全通过，已进入降级/重试流程。"
    return {
        "quiz_quality_report": report.model_dump(),
        "quiz_generation_status": status,
    }


def quiz_retry_agent(state: AgentState) -> dict[str, Any]:
    retry_count = min(QUIZ_MAX_RETRY, int(state.get("quiz_retry_count", 0) or 0) + 1)
    return {
        "quiz_retry_count": retry_count,
        "graph_warnings": ["quiz_quality_node requested one expanded RAG retry."],
    }


def quiz_output_agent(state: AgentState) -> dict[str, Any]:
    context = QuizGenerationContext.model_validate(state.get("quiz_context") or {})
    report = QuizQualityReport.model_validate(state.get("quiz_quality_report") or {})
    status = dict(state.get("quiz_generation_status") or {})
    status.update(
        {
            "quality_passed": report.passed,
            "retry_count": int(state.get("quiz_retry_count", 0) or 0),
            "focus_points": context.focus_points,
            "rag_doc_count": len(state.get("quiz_rag_docs") or []),
            "quality_issues": report.issues,
        }
    )
    final_answer = build_quiz_final_answer(context=context, status=status, report=report)
    return {
        "quiz_generation_status": status,
        "final_answer": final_answer,
    }
