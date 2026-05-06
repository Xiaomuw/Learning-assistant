from __future__ import annotations

from typing import Any

from app.application.chat.messages import build_assistant_message, build_user_message
from app.domains.memory.service import update_memories_after_turn
from app.infrastructure.db.repositories.sessions import append_chat_turn_record
from app.shared.schemas.subject import DEFAULT_SUBJECTS


def persist_chat_session(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    question: str,
    final_state: dict[str, Any],
) -> dict[str, Any]:
    """Persist the user turn, assistant turn, latest quiz, and memory snapshot."""
    user_message = build_user_message(question)
    assistant_message = build_assistant_message(final_state)
    memory_updates = update_memories_after_turn(
        previous_session_memory=final_state.get("session_memory"),
        short_term_messages=final_state.get("short_term_messages", []),
        short_term_context=final_state.get("short_term_context", ""),
        long_term_context=final_state.get("long_term_context", ""),
        question=question,
        question_type=final_state.get("question_type", "concept"),
        explanation=final_state.get("explanation", {}),
        quiz_items=final_state.get("quiz_items", []) or [],
        final_answer=final_state.get("final_answer", "") or assistant_message.get("content", ""),
        subject_name=final_state.get("subject_name", str(DEFAULT_SUBJECTS[0]["name"])),
        model_name=str(final_state.get("model_name", "") or "").strip() or None,
    )
    final_state.update(memory_updates)
    session = append_chat_turn_record(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        title=question[:50] or "新对话",
        user_message=user_message,
        assistant_message=assistant_message,
        latest_quiz=final_state.get("quiz_items") or [],
        session_memory=memory_updates["session_memory"],
    )
    return session.model_dump()
