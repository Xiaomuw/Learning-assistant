from __future__ import annotations

import os

from app.application.errors import ServiceUnavailableError, ValidationError
from app.infrastructure.db.repositories.settings import (
    set_app_setting_record,
)
from app.infrastructure.llm.provider import (
    build_model_option,
    list_selectable_chat_models,
    validate_chat_model_access,
)
from app.infrastructure.llm.config import (
    get_embedding_model,
    get_locked_chat_model,
    get_model_switching_status,
    is_model_switching_enabled,
)
from app.services.runtime_models import ensure_available_active_chat_model
from app.shared.schemas.contracts import ModelConfigSnapshot, ModelOptionRecord


def _locked_model_config_snapshot() -> ModelConfigSnapshot:
    locked_model = get_locked_chat_model()
    option = build_model_option(locked_model) or {
        "id": locked_model,
        "label": locked_model,
        "provider": "OpenAI",
        "family": "GPT",
    }
    return ModelConfigSnapshot(
        current_model=locked_model,
        embedding_model=get_embedding_model(),
        available_models=[ModelOptionRecord.model_validate(option)],
        model_switching_enabled=False,
        model_switching_status=get_model_switching_status(),
        locked_model=locked_model,
    )


def build_model_config_response(*, force_refresh: bool = False) -> ModelConfigSnapshot:
    if not is_model_switching_enabled():
        return _locked_model_config_snapshot()

    current_model = ensure_available_active_chat_model(force_refresh=force_refresh)
    available_models = list_selectable_chat_models(force_refresh=force_refresh)

    if current_model not in {item["id"] for item in available_models}:
        current_option = build_model_option(current_model)
        if current_option:
            available_models = [current_option, *available_models]

    if not available_models:
        raise ServiceUnavailableError("当前账号未获取到可用聊天模型")

    return ModelConfigSnapshot(
        current_model=current_model,
        embedding_model=get_embedding_model(),
        available_models=[ModelOptionRecord.model_validate(item) for item in available_models],
        model_switching_enabled=True,
        model_switching_status=get_model_switching_status(),
        locked_model=get_locked_chat_model(),
    )


def update_active_chat_model(chat_model: str) -> ModelConfigSnapshot:
    locked_model = get_locked_chat_model()
    if not is_model_switching_enabled():
        if chat_model != locked_model:
            option = build_model_option(locked_model) or {}
            label = str(option.get("label") or locked_model)
            raise ValidationError(f"模型选择功能待开发，当前仅支持 {label}")
        set_app_setting_record("chat_model", locked_model)
        return _locked_model_config_snapshot()

    available_models = list_selectable_chat_models(force_refresh=True)
    if not available_models:
        raise ServiceUnavailableError("当前账号未获取到可用聊天模型")

    available_ids = {item["id"] for item in available_models}
    if chat_model not in available_ids:
        raise ValidationError("该模型当前不可选，系统只展示当前账号真实可用的聊天模型")

    is_valid, error_message = validate_chat_model_access(chat_model)
    if not is_valid:
        raise ValidationError(f"该模型当前账号不可用或响应不稳定：{error_message}")

    set_app_setting_record("chat_model", chat_model)
    return build_model_config_response(force_refresh=True)
