"""
Model Config API
================
提供聊天模型配置接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.application.model_config.service import (
    build_model_config_response,
    update_active_chat_model,
)
from app.infrastructure.llm.config import (
    get_known_model_api_keys,
    get_locked_chat_model,
    get_model_switching_status,
    is_model_switching_enabled,
)
from app.infrastructure.llm.profile import get_model_profile
from app.infrastructure.llm.provider import validate_chat_model_access
from app.services.runtime_models import resolve_active_chat_model
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.http_errors import to_http_exception
from app.application.errors import ApplicationError
from app.shared.schemas.contracts import ModelConfigSnapshot

router = APIRouter()


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str
    family: str


class ModelConfigResponse(BaseModel):
    current_model: str
    embedding_model: str
    available_models: list[ModelOption]
    model_switching_enabled: bool = False
    model_switching_status: str = "development"
    locked_model: str = ""


class ModelConfigUpdateRequest(BaseModel):
    chat_model: str = Field(..., min_length=1, description="新的聊天模型 ID")


class ModelHealthResponse(BaseModel):
    chat_model: str
    chat_model_ok: bool
    chat_model_error: str | None = None
    model_switching_enabled: bool = False
    model_switching_status: str = "development"
    supports_tool_calling: bool = True
    supports_structured_output: bool = True


def _redact_model_error(error_message: str | None) -> str | None:
    if not error_message:
        return None
    redacted = error_message
    for access_key in get_known_model_api_keys():
        redacted = redacted.replace(access_key, "[redacted]")
    return redacted


def _to_model_config_response(payload: ModelConfigSnapshot) -> ModelConfigResponse:
    return ModelConfigResponse(
        current_model=payload.current_model,
        embedding_model=payload.embedding_model,
        available_models=[ModelOption(**item.model_dump()) for item in payload.available_models],
        model_switching_enabled=payload.model_switching_enabled,
        model_switching_status=payload.model_switching_status,
        locked_model=payload.locked_model,
    )


@router.get("/settings/model", response_model=ModelConfigResponse)
async def get_model_config(_: AuthenticatedUser = Depends(require_current_user)):
    """获取当前模型配置与可选模型列表。"""
    try:
        payload = build_model_config_response()
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _to_model_config_response(payload)


@router.put("/settings/model", response_model=ModelConfigResponse)
async def update_model_config(
    body: ModelConfigUpdateRequest,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """更新当前聊天模型。"""
    try:
        payload = update_active_chat_model(body.chat_model)
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _to_model_config_response(payload)


@router.get("/settings/model/health", response_model=ModelHealthResponse)
async def check_model_health(
    chat_model: str | None = Query(default=None),
    _: AuthenticatedUser = Depends(require_current_user),
):
    """轻量验证当前或指定聊天模型是否可用。"""
    selected_model = (
        chat_model
        if chat_model and is_model_switching_enabled()
        else resolve_active_chat_model(get_locked_chat_model())
    )
    profile = get_model_profile(selected_model)
    ok, error_message = validate_chat_model_access(selected_model)
    return ModelHealthResponse(
        chat_model=selected_model,
        chat_model_ok=ok,
        chat_model_error=_redact_model_error(error_message),
        model_switching_enabled=is_model_switching_enabled(),
        model_switching_status=get_model_switching_status(),
        supports_tool_calling=profile.supports_tool_calling,
        supports_structured_output=profile.supports_structured_output,
    )
