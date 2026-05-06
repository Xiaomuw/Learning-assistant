from __future__ import annotations

import os

from app.infrastructure.db.repositories.settings import get_app_setting_record, set_app_setting_record
from app.infrastructure.llm.config import get_locked_chat_model, is_model_switching_enabled
from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, list_selectable_chat_models

LEGACY_PLACEHOLDER_MODELS = {
    "openai-gpt-oss-20b",
    "openai-gpt-oss-120b",
}


def resolve_active_chat_model(default_model: str | None = None) -> str:
    if not is_model_switching_enabled():
        return get_locked_chat_model()

    env_model = (os.getenv("OPENAI_MODEL") or "").strip()
    configured = (
        get_app_setting_record("chat_model", default_model or DEFAULT_CHAT_MODEL).value
        or ""
    ).strip()

    # Historical seed data used older defaults as placeholders. When the
    # environment explicitly pins a different model, treat those placeholders as
    # "not configured" so locked-model keys can override stale DB settings.
    if configured and not (
        configured in {DEFAULT_CHAT_MODEL, *LEGACY_PLACEHOLDER_MODELS}
        and env_model
        and env_model != configured
    ):
        return configured

    return env_model or default_model or DEFAULT_CHAT_MODEL


def ensure_available_active_chat_model(*, force_refresh: bool = False) -> str:
    current_model = resolve_active_chat_model(DEFAULT_CHAT_MODEL)
    if not is_model_switching_enabled():
        return current_model

    if not force_refresh:
        return current_model

    available_models = list_selectable_chat_models(force_refresh=force_refresh)
    if not available_models:
        return current_model

    available_ids = {item["id"] for item in available_models}
    if current_model in available_ids:
        return current_model

    preferred_model = DEFAULT_CHAT_MODEL if DEFAULT_CHAT_MODEL in available_ids else available_models[0]["id"]
    set_app_setting_record("chat_model", preferred_model)
    return preferred_model
