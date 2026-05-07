"""
Memory Service
==============
对 API / Agents 暴露统一的记忆装配与会话摘要更新入口。
"""

from __future__ import annotations

from typing import Any

from app.domains.memory.long_term import build_long_term_context
from app.domains.memory.session_summary import (
    build_session_memory_context,
    normalize_session_memory,
    update_session_memory,
)
from app.domains.memory.short_term import build_short_term_context, extract_short_term_messages
from app.domains.memory.gateway import load_chat_session, load_user_memory, load_user_profile


def build_request_context(user_id: str, session_id: str) -> dict[str, Any]:
    """
    组装请求进入 LangGraph 前所需的三层记忆上下文与用户画像。
    """
    memory = load_user_memory(user_id)
    user_profile = load_user_profile(user_id)
    existing_session = load_chat_session(user_id, session_id)
    short_term_messages = extract_short_term_messages(existing_session)
    short_term_context = build_short_term_context(short_term_messages)
    session_memory = normalize_session_memory((existing_session or {}).get("session_memory"))
    session_memory_context = build_session_memory_context(session_memory)
    long_term_context = build_long_term_context(user_profile, memory)

    return {
        "memory": memory,
        "user_profile": user_profile,
        "existing_session": existing_session,
        "short_term_messages": short_term_messages,
        "short_term_context": short_term_context,
        "session_memory": session_memory,
        "session_memory_context": session_memory_context,
        "long_term_context": long_term_context,
    }


def update_memories_after_turn(
    *,
    previous_session_memory: dict[str, Any] | None,
    short_term_messages: list[dict[str, Any]],
    short_term_context: str,
    long_term_context: str,
    question: str,
    question_type: str,
    explanation: dict[str, Any],
    quiz_items: list[dict[str, Any]],
    final_answer: str,
    subject_name: str,
    quiz_request: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    在一轮问答结束后更新中期会话摘要，并返回 prompt 可直接使用的上下文。
    """
    next_session_memory = update_session_memory(
        previous_session_memory=previous_session_memory,
        short_term_messages=short_term_messages,
        short_term_context=short_term_context,
        long_term_context=long_term_context,
        question=question,
        question_type=question_type,
        explanation=explanation,
        quiz_items=quiz_items,
        quiz_request=quiz_request,
        final_answer=final_answer,
        subject_name=subject_name,
        model_name=model_name,
    )

    return {
        "session_memory": next_session_memory,
        "session_memory_context": build_session_memory_context(next_session_memory),
    }
