from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.mastery.service import get_mastery
from app.domains.teaching.policy import build_teaching_response, decide_teaching_policy
from app.services.code_execution import execute_code
from app.shared.schemas.state import AgentState


def teaching_state_agent(state: AgentState) -> dict[str, Any]:
    """Decide the teaching protocol branch for this turn."""
    user_id = str(state.get("user_id", "") or "")
    subject_id = str(state.get("subject_id", "general") or "general")
    question = str(state.get("question", "") or "")
    question_type = str(state.get("question_type", "concept") or "concept")
    session_memory = dict(state.get("session_memory") or {})
    memory = dict(state.get("memory") or {})
    try:
        mastery = get_mastery(user_id=user_id, subject_id=subject_id, limit=100)
        mastery_items = [item.model_dump() for item in mastery.items]
    except Exception as exc:
        logger.warning(f"⚠️ 教学策略读取掌握度失败，使用空档案: {type(exc).__name__}")
        mastery_items = []

    decision = decide_teaching_policy(
        question=question,
        router_type=question_type,
        memory=memory,
        session_memory=session_memory,
        mastery_items=mastery_items,
    )
    update: dict[str, Any] = {
        "teaching_input_type": decision.teaching_input_type,
        "teaching_user_state": decision.teaching_user_state,
        "teaching_knowledge_point": decision.knowledge_point,
        "used_analogy": decision.used_analogy,
        "stuck_count": decision.stuck_count,
        "teaching_phase": "decided",
        "last_teaching_action": decision.last_teaching_action,
        "knowledge_mastery": mastery_items,
    }
    if decision.teaching_input_type in {"compare", "application"}:
        update["question_type"] = decision.teaching_input_type
    logger.info(
        f"🎓 teaching_state | type={decision.teaching_input_type} "
        f"| user_state={decision.teaching_user_state} | kp={decision.knowledge_point}"
    )
    return update


def teaching_response_agent(state: AgentState) -> dict[str, Any]:
    """Apply the teaching protocol to the final answer shape."""
    question = str(state.get("question", "") or "")
    session_memory = dict(state.get("session_memory") or {})
    memory = dict(state.get("memory") or {})
    decision = decide_teaching_policy(
        question=question,
        router_type=str(state.get("question_type", "concept") or "concept"),
        memory=memory,
        session_memory=session_memory,
        mastery_items=list(state.get("knowledge_mastery") or []),
    )
    code_result = execute_code(question).model_dump()
    update = build_teaching_response(
        decision,
        question=question,
        existing_explanation=state.get("explanation") or {},
        existing_final_answer=str(state.get("final_answer", "") or ""),
        code_result=code_result,
    )
    pending_check = update.get("pending_check")
    next_session_memory = {
        **session_memory,
        "teaching_phase": update.get("teaching_phase", ""),
        "last_teaching_action": update.get("last_teaching_action", ""),
        "stuck_count": decision.stuck_count,
        "used_analogies": _append_used_analogy(
            session_memory.get("used_analogies"),
            decision.knowledge_point,
            decision.used_analogy,
        ),
    }
    if isinstance(pending_check, dict) and pending_check:
        next_session_memory["pending_check"] = pending_check
    elif pending_check == {}:
        next_session_memory.pop("pending_check", None)

    update.update(
        {
            "teaching_input_type": decision.teaching_input_type,
            "teaching_user_state": decision.teaching_user_state,
            "teaching_knowledge_point": decision.knowledge_point,
            "used_analogy": decision.used_analogy,
            "stuck_count": decision.stuck_count,
            "code_execution_result": code_result,
            "session_memory": next_session_memory,
        }
    )
    logger.info(
        f"🎓 teaching_response | action={update.get('last_teaching_action')} "
        f"| waiting={update.get('teaching_waiting_for_user')}"
    )
    return update


def _append_used_analogy(raw: Any, knowledge_point: str, analogy: str) -> list[dict[str, str]]:
    existing: list[dict[str, str]] = []
    for item in list(raw or []):
        if isinstance(item, dict):
            kp = str(item.get("knowledge_point", "") or "")
            text = str(item.get("analogy", "") or "")
            if kp and text:
                existing.append({"knowledge_point": kp, "analogy": text})
    if knowledge_point and analogy and not any(item["knowledge_point"] == knowledge_point for item in existing):
        existing.insert(0, {"knowledge_point": knowledge_point, "analogy": analogy})
    return existing[:10]
