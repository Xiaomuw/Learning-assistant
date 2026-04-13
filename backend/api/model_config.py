"""
Model Config API
================
提供可切换的聊天模型配置接口。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.repositories import set_app_setting
from tools.model_provider import (
    DEFAULT_CHAT_MODEL,
    get_active_chat_model,
    list_selectable_chat_models,
    validate_chat_model_access,
)

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


class ModelConfigUpdateRequest(BaseModel):
    chat_model: str = Field(..., min_length=1, description="新的聊天模型 ID")


def _build_model_config_response(force_refresh: bool = False) -> ModelConfigResponse:
    available_models = list_selectable_chat_models(force_refresh=force_refresh)

    if not available_models:
        raise HTTPException(status_code=503, detail="当前未获取到可用模型列表")

    available_ids = {item["id"] for item in available_models}
    current_model = get_active_chat_model(DEFAULT_CHAT_MODEL)

    if current_model not in available_ids:
        preferred_model = (
            DEFAULT_CHAT_MODEL if DEFAULT_CHAT_MODEL in available_ids else available_models[0]["id"]
        )
        set_app_setting("chat_model", preferred_model)
        current_model = preferred_model

    return ModelConfigResponse(
        current_model=current_model,
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        available_models=[ModelOption(**item) for item in available_models],
    )


@router.get("/settings/model", response_model=ModelConfigResponse)
async def get_model_config():
    """获取当前模型配置与可选模型列表。"""
    return _build_model_config_response()


@router.put("/settings/model", response_model=ModelConfigResponse)
async def update_model_config(body: ModelConfigUpdateRequest):
    """更新当前聊天模型。"""
    available_models = list_selectable_chat_models(force_refresh=True)
    available_ids = {item["id"] for item in available_models}

    if body.chat_model not in available_ids:
        raise HTTPException(
            status_code=400,
            detail="该模型当前不可选，系统只允许 GPT / Gemini / Qwen / Llama / GLM / Kimi / DeepSeek 等非 Claude 模型",
        )

    is_valid, error_message = validate_chat_model_access(body.chat_model)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"该模型当前账号不可用或响应不稳定：{error_message}",
        )

    set_app_setting("chat_model", body.chat_model)
    return _build_model_config_response(force_refresh=True)
