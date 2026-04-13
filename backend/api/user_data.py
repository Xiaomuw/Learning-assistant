"""
用户数据 API
============
为 H5 前端提供学习记忆、历史对话、最新题包。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.repositories import (
    delete_chat_session,
    get_latest_quiz,
    get_user_memory,
    get_user_profile,
    list_chat_sessions,
    save_user_profile,
)

router = APIRouter()


class MemoryResponse(BaseModel):
    weak_points: list[str] = Field(default_factory=list)
    error_count: dict[str, int] = Field(default_factory=dict)
    recent_topics: list[str] = Field(default_factory=list)
    last_session: str = ""


class SessionResponse(BaseModel):
    id: str
    user_id: str
    subject_id: str
    title: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    latest_quiz: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class LatestQuizResponse(BaseModel):
    quiz_items: list[dict[str, Any]] = Field(default_factory=list)


class UserProfileResponse(BaseModel):
    user_id: str
    display_name: str = ""
    agent_style_name: str = ""
    agent_style_prompt: str = ""
    onboarding_completed: bool = False


class UserProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    agent_style_name: str | None = Field(default=None, max_length=120)
    agent_style_prompt: str | None = Field(default=None, max_length=4000)
    onboarding_completed: bool | None = None


@router.get("/users/{user_id}/memory", response_model=MemoryResponse)
async def get_memory(user_id: str):
    return get_user_memory(user_id)


@router.get("/users/{user_id}/profile", response_model=UserProfileResponse)
async def get_profile(user_id: str):
    return get_user_profile(user_id)


@router.put("/users/{user_id}/profile", response_model=UserProfileResponse)
async def update_profile(user_id: str, body: UserProfileUpdateRequest):
    existing = get_user_profile(user_id)

    next_profile = {
        "display_name": (
            body.display_name
            if body.display_name is not None
            else existing.get("display_name", "")
        ),
        "agent_style_name": (
            body.agent_style_name
            if body.agent_style_name is not None
            else existing.get("agent_style_name", "")
        ),
        "agent_style_prompt": (
            body.agent_style_prompt
            if body.agent_style_prompt is not None
            else existing.get("agent_style_prompt", "")
        ),
        "onboarding_completed": (
            body.onboarding_completed
            if body.onboarding_completed is not None
            else existing.get("onboarding_completed", False)
        ),
    }

    return save_user_profile(user_id, next_profile)


@router.get("/users/{user_id}/sessions", response_model=list[SessionResponse])
async def get_sessions(user_id: str):
    return list_chat_sessions(user_id=user_id)


@router.delete("/users/{user_id}/sessions/{session_id}")
async def remove_session(user_id: str, session_id: str):
    deleted = delete_chat_session(user_id=user_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="聊天记录不存在")

    return {"message": "聊天记录已删除"}


@router.get("/users/{user_id}/quiz/latest", response_model=LatestQuizResponse)
async def get_latest_quiz_for_user(user_id: str):
    return {"quiz_items": get_latest_quiz(user_id)}
