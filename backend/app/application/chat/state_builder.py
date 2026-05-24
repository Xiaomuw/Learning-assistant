from __future__ import annotations

from uuid import uuid4

from loguru import logger

from app.domains.memory.service import build_request_context
from app.infrastructure.db.repositories.subjects import get_subject_record
from app.orchestration.graphs.shared.schemas import SourcePolicy
from app.services.runtime_models import resolve_active_chat_model
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id
from app.shared.schemas.state import AgentState


def build_initial_state(
    *,
    user_id: str,
    session_id: str,
    question: str,
    subject_id: str,
    request_mode: str,
    knowledge_base_mode: str = "auto",
    auto_web_fallback: bool = True,
    thinking_mode: bool = False,
    allow_web: bool = False,
    client_request_id: str | None = None,
    request_id: str | None = None,
) -> AgentState:
    """Build the LangGraph state for a chat turn."""
    context = build_request_context(user_id, session_id)
    normalized_subject_id = normalize_subject_id(subject_id)
    subject = get_subject_record(normalized_subject_id)
    fallback_subject = DEFAULT_SUBJECTS[0]
    subject_name = subject.name if subject else str(fallback_subject["name"])
    subject_description = subject.description if subject else str(fallback_subject["description"])
    normalized_client_request_id = str(client_request_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    message_id = normalized_client_request_id or normalized_request_id or str(uuid4())
    normalized_request_id = normalized_request_id or message_id
    normalized_knowledge_base_mode = _normalize_knowledge_base_mode(knowledge_base_mode)

    initial_state: AgentState = {
        "user_id": user_id,
        "session_id": session_id,
        "message_id": message_id,
        "request_id": normalized_request_id,
        "client_request_id": normalized_client_request_id,
        "subject_id": normalized_subject_id,
        "subject_name": subject_name,
        "subject_description": subject_description,
        "selected_subject_id": normalized_subject_id,
        "selected_subject_name": subject_name,
        "selected_subject_description": subject_description,
        "question": question,
        "request_mode": request_mode,
        "knowledge_base_mode": normalized_knowledge_base_mode,
        "auto_web_fallback": bool(auto_web_fallback),
        "thinking_mode": thinking_mode,
        "allow_web": bool(allow_web),
        "web_search_requested": bool(allow_web),
        "memory": context["memory"],
        "user_style_name": "",
        "user_style_prompt": "",
        "short_term_messages": context["short_term_messages"],
        "short_term_context": context["short_term_context"],
        "session_memory": context["session_memory"],
        "session_memory_context": context["session_memory_context"],
        "long_term_context": context["long_term_context"],
        "model_name": resolve_active_chat_model(),
    }
    if normalized_knowledge_base_mode == "strict":
        initial_state["notebook_policy"] = "strict"
        initial_state["notebook_required"] = True
        initial_state["source_policy"] = SourcePolicy.NOTEBOOK_ONLY.value
    elif normalized_knowledge_base_mode == "current":
        initial_state["notebook_policy"] = "required"
        initial_state["notebook_required"] = False
        initial_state["source_policy"] = SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    elif allow_web:
        initial_state["source_policy"] = SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value
    logger.info(
        f"📋 初始 State 构建完成 | user={user_id} | subject={subject_name} | "
        f"short_term_messages={len(context['short_term_messages'])} | "
        f"session_topic={context['session_memory'].get('active_topic', '') or 'n/a'} | "
        f"long_term_topics={len(context['memory'].get('recent_topics', []))}"
    )
    return initial_state


def _normalize_knowledge_base_mode(value: str | None) -> str:
    candidate = str(value or "auto").strip().lower()
    if candidate in {"auto", "current", "strict"}:
        return candidate
    return "auto"
