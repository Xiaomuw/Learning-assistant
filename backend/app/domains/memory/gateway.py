"""Memory persistence gateway.

为 memory 领域提供一组窄适配读写接口，避免领域层直接变成半个仓储工具箱。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.infrastructure.db.repositories.sessions import get_chat_session_record
from app.infrastructure.db.repositories.users import (
    get_user_memory_record,
    get_user_profile_record,
    save_user_memory_record,
)
from app.shared.schemas.state import Memory

EMPTY_MEMORY: Memory = {
    "weak_points": [],
    "error_count": {},
    "recent_topics": [],
    "last_session": "",
}


def load_user_memory(user_id: str) -> Memory:
    try:
        memory = get_user_memory_record(user_id).model_dump()
        logger.info(
            f"📂 加载用户 {user_id} 记忆成功 | "
            f"weak={len(memory['weak_points'])} | "
            f"topics={len(memory['recent_topics'])}"
        )
        return memory
    except Exception as exc:
        logger.warning(f"⚠️ 读取用户 {user_id} 记忆失败: {exc}")
        return dict(EMPTY_MEMORY)


def save_user_memory_state(user_id: str, memory: Memory) -> None:
    try:
        from app.shared.schemas.contracts import UserMemoryRecord

        save_user_memory_record(user_id, UserMemoryRecord.model_validate(dict(memory)))
        logger.info(f"💾 用户 {user_id} 记忆已保存到数据库")
    except Exception as exc:
        logger.warning(f"⚠️ 保存用户 {user_id} 记忆失败: {exc}")


def load_user_profile(user_id: str) -> dict[str, Any]:
    try:
        return get_user_profile_record(user_id).model_dump()
    except Exception as exc:
        logger.warning(f"⚠️ 读取用户 {user_id} Profile 失败: {exc}")
        return {
            "display_name": "",
            "agent_style_name": "",
            "agent_style_prompt": "",
            "onboarding_completed": False,
        }


def load_chat_session(user_id: str, session_id: str) -> dict[str, Any] | None:
    try:
        record = get_chat_session_record(user_id, session_id)
        return record.model_dump() if record else None
    except Exception as exc:
        logger.warning(f"⚠️ 读取会话 {session_id} 失败: {exc}")
        return None
