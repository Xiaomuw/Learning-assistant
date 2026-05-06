from __future__ import annotations

import re
from typing import Any

from app.domains.memory.short_term import is_context_dependent_question


def _normalize_preview(text: str, max_length: int = 40) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def extract_recent_topic(
    short_term_messages: list[dict[str, Any]],
    session_memory: dict[str, Any] | None,
    memory: dict[str, Any],
) -> str:
    if session_memory:
        active_topic = str(session_memory.get("active_topic", "") or "").strip()
        if active_topic:
            return active_topic
    for message in reversed(short_term_messages):
        explanation = message.get("explanation") or {}
        topic = str(explanation.get("topic", "") or "").strip()
        if topic:
            return topic
    for message in reversed(short_term_messages):
        content = _normalize_preview(str(message.get("content", "")))
        if content:
            return content
    recent_topics = list(memory.get("recent_topics", []) or [])
    if recent_topics:
        return str(recent_topics[0]).strip()
    return ""


def build_contextual_query(
    question: str,
    short_term_messages: list[dict[str, Any]],
    session_memory: dict[str, Any] | None,
    memory: dict[str, Any],
) -> str:
    normalized_question = re.sub(r"\s+", " ", (question or "")).strip()
    if not normalized_question:
        return ""
    if not is_context_dependent_question(normalized_question):
        return normalized_question
    anchor = extract_recent_topic(short_term_messages, session_memory, memory)
    if not anchor or anchor in normalized_question:
        return normalized_question
    return f"{anchor} {normalized_question}"
