"""
出题 Agent
==========
职责：
  根据当前知识点和用户掌握情况，生成一组 4 选 1 单选题。

策略：
  1. 优先从本地真题题库中检索匹配题目
  2. 若题库不足，则由 AI 继续补齐
  3. 输出统一的单选题结构，供练习页与推荐卡复用
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.practice.service import (
    build_mixed_practice_items_with_status,
    determine_difficulty,
    infer_topic_from_question,
)
from app.shared.schemas.contracts import PracticeRecommendation
from app.shared.schemas.state import AgentState

QUIZ_COUNT = 2


def _quiz_item_source_type(item: PracticeRecommendation | dict[str, Any]) -> str:
    if isinstance(item, PracticeRecommendation):
        return item.source_type or "unknown"
    return str(item.get("source_type", "unknown") or "unknown")


def _quiz_item_payload(item: PracticeRecommendation | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, PracticeRecommendation):
        return item.model_dump()
    return dict(item)


def quiz_agent(state: AgentState) -> dict[str, Any]:
    explanation = state.get("explanation", {})
    memory = state.get("memory", {})
    question = state.get("question", "")

    subject_id = state.get("subject_id", "general")
    subject_name = state.get("subject_name", "综合")
    topic = explanation.get("topic") or infer_topic_from_question(question, subject_name)
    error_count = memory.get("error_count", {})
    short_term_context = state.get("short_term_context", "（当前会话暂无历史上下文）")
    session_memory_context = state.get("session_memory_context", "（当前会话暂无中期摘要）")
    long_term_context = state.get("long_term_context", "（暂无长期学习记忆）")
    user_style_name = state.get("user_style_name", "")
    user_style_prompt = state.get("user_style_prompt", "")
    model_name = str(state.get("model_name", "") or "").strip() or None

    logger.info(
        f"✏️ 出题 Agent 开始 | subject={subject_id} | topic='{topic}' | question='{question[:50]}…'"
    )

    difficulty = determine_difficulty(topic, error_count)

    try:
        generation_result = build_mixed_practice_items_with_status(
            subject_id=subject_id,
            subject_name=subject_name,
            topic=topic,
            difficulty=difficulty,
            count=QUIZ_COUNT,
            original_question=question,
            user_style_name=user_style_name,
            user_style_prompt=user_style_prompt,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )
        quiz_items = generation_result.items
        quiz_generation_status = generation_result.status
        quiz_payloads = [_quiz_item_payload(item) for item in quiz_items]

        fallback_count = int(quiz_generation_status.get("fallback_count") or 0)
        partial = bool(quiz_generation_status.get("partial", False))
        degraded_reason = str(quiz_generation_status.get("degraded_reason", "") or "").strip()
        final_answer = (
            f"我已经围绕「{topic}」准备了 {len(quiz_items)} 道{difficulty}单选题，"
            "你可以直接去刷题页继续做。"
        )
        if fallback_count or partial:
            final_answer += f" 其中 {fallback_count} 道使用备用题补齐。"
        if partial and degraded_reason:
            final_answer += f" 本轮部分降级原因：{degraded_reason}"
        logger.info(
            f"✏️ 出题完成 | 共 {len(quiz_items)} 道 | "
            f"来源={[_quiz_item_source_type(item) for item in quiz_items]}"
        )
    except Exception as exc:
        logger.error(f"❌ 出题 Agent 调用失败: {exc}")
        quiz_payloads = []
        quiz_generation_status = {
            "requested_count": QUIZ_COUNT,
            "generated_count": 0,
            "question_bank_count": 0,
            "ai_count": 0,
            "fallback_count": 0,
            "partial": True,
            "degraded_reason": str(exc),
        }
        final_answer = (
            f"关于「{topic}」的单选题生成失败了。"
            "这次我没有保存残缺题目，你可以稍后重试。"
        )

    return {
        "quiz_items": quiz_payloads,
        "quiz_generation_status": quiz_generation_status,
        "final_answer": final_answer,
    }
