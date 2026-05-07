"""
LLM Provider façade.

真实职责已经拆到 config / catalog / clients：
- config：环境变量、密钥别名、基础超时配置
- catalog：远程模型目录、过滤、排序和缓存
- clients：Chat / Embedding 客户端创建与轻量健康探测

本文件保留为基础设施层公开入口，便于现有调用方和测试继续 patch
provider.validate_*，同时避免 provider 重新变回巨型模块。
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.llm.catalog import (
    _MODEL_ACCESS_CACHE,
    _MODEL_CACHE,
    _MODEL_CANDIDATE_CACHE,
    build_model_option,
    list_configured_chat_models,
)
from app.infrastructure.llm.clients import (
    get_active_chat_model,
    get_chat_llm,
    get_embeddings,
    validate_chat_model_access,
    validate_embedding_model_access,
)
from app.infrastructure.llm.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_DO_BASE_URL,
    ensure_model_env_aliases,
    get_embedding_check_ctx_length as _get_embedding_check_ctx_length,
    get_embedding_model_connection,
    get_model_access_key,
    get_openai_compatible_base_url,
    get_pydo_client,
)
from app.infrastructure.llm.profile import get_model_profile as _get_model_profile
from app.shared.schemas.model_profile import ModelProfile


def list_selectable_chat_models(force_refresh: bool = False) -> list[dict[str, str]]:
    """返回当前产品开放的聊天模型列表。

    模型可见性不再依赖单一 provider 的远程目录；真正可用性在切换和
    health check 时由 validate_chat_model_access 按 provider 验证。
    """
    return list_configured_chat_models()


def get_model_profile(model_name: str | None = None) -> ModelProfile:
    """返回当前聊天模型的静态能力画像。"""
    return _get_model_profile(model_name or get_active_chat_model(DEFAULT_CHAT_MODEL))


def is_supported_chat_model(model_id: str) -> bool:
    return model_id in {item["id"] for item in list_selectable_chat_models()}


def build_model_health_snapshot(*, chat_model: str | None = None) -> dict[str, Any]:
    """Return a non-sensitive health snapshot for local diagnostics."""
    selected_chat_model = chat_model or get_active_chat_model(DEFAULT_CHAT_MODEL)
    embedding_connection = get_embedding_model_connection()
    profile = get_model_profile(selected_chat_model)
    chat_ok, chat_error = validate_chat_model_access(selected_chat_model)
    embedding_ok, embedding_error = validate_embedding_model_access(embedding_connection.model_id)
    return {
        "base_url": get_openai_compatible_base_url(),
        "embedding_base_url": embedding_connection.base_url,
        "chat_model": selected_chat_model,
        "embedding_model": embedding_connection.model_id,
        "chat_model_ok": chat_ok,
        "chat_model_error": chat_error,
        "embedding_model_ok": embedding_ok,
        "embedding_model_error": embedding_error,
        "supports_tool_calling": profile.supports_tool_calling,
        "supports_structured_output": profile.supports_structured_output,
    }
