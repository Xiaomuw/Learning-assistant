"""
选择题判题 Agent
================
职责：
  识别用户贴进聊天页的文本选择题，并给出正确选项与解析。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.practice.service import solve_mcq_question
from app.shared.schemas.state import AgentState


def mcq_solver_agent(state: AgentState) -> dict[str, Any]:
    question = state.get("question", "")
    subject_name = state.get("subject_name", "通用知识")
    short_term_context = state.get("short_term_context", "（当前会话暂无历史上下文）")
    session_memory_context = state.get("session_memory_context", "（当前会话暂无中期摘要）")
    long_term_context = state.get("long_term_context", "（暂无长期学习记忆）")
    user_style_name = state.get("user_style_name", "")
    user_style_prompt = state.get("user_style_prompt", "")
    model_name = str(state.get("model_name", "") or "").strip() or None

    logger.info(f"📝 选择题判题 Agent 开始 | question={question[:80]}…")

    try:
        result = solve_mcq_question(
            question=question,
            subject_name=subject_name,
            user_style_name=user_style_name,
            user_style_prompt=user_style_prompt,
            short_term_context=short_term_context,
            session_memory_context=session_memory_context,
            long_term_context=long_term_context,
            model_name=model_name,
        )
        logger.info("📝 选择题判题完成")
        return result
    except Exception as exc:
        logger.error(f"❌ 选择题判题失败: {exc}")
        return {
            "explanation": {
                "topic": "选择题判题失败",
                "thinking": "抱歉，这道选择题暂时没识别成功。",
                "steps": ["请尽量按“题干 + A/B/C/D 选项”格式重新发送。"],
                "mistakes": "选项结构不完整时会影响判题准确性。",
                "similar": ["重新整理题干", "补全选项"],
            },
            "final_answer": "这道选择题我暂时没判出来，请把题干和 A/B/C/D 四个选项完整发给我。",
        }
