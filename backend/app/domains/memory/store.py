"""Deprecated shim for memory persistence helpers.

正式入口已迁移到 `app.domains.memory.gateway`。
"""

from app.domains.memory.gateway import (  # noqa: F401
    EMPTY_MEMORY,
    load_chat_session,
    load_user_memory,
    load_user_profile,
    save_user_memory_state,
)
