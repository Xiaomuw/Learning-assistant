"""
用户数据 API
============
为 H5 前端提供学习记忆、历史对话、最新题包。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.application.errors import ApplicationError
from app.application.user_data.service import (
    get_latest_quiz_bundle as get_latest_quiz_bundle_service,
    get_knowledge_mastery as get_knowledge_mastery_service,
    get_memory as get_memory_service,
    get_profile as get_profile_service,
    get_sessions as get_sessions_service,
    remove_session as remove_session_service,
    update_profile as update_profile_service,
)
from app.interfaces.auth.dependencies import AuthenticatedUser, verify_user_access
from app.interfaces.http_errors import to_http_exception
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()


class MemoryResponse(BaseModel):
    weak_points: list[str] = Field(default_factory=list)
    error_count: dict[str, int] = Field(default_factory=dict)
    recent_topics: list[str] = Field(default_factory=list)
    last_session: str = ""


class KnowledgeMasteryItemResponse(BaseModel):
    user_id: str
    subject_id: str = DEFAULT_SUBJECT_ID
    knowledge_point: str
    exposure_count: int = 0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    mastery_score: float = 0.0
    mastery_level: str = "weak"
    last_seen_at: str = ""
    last_practiced_at: str = ""
    updated_at: str = ""


class KnowledgeMasteryResponse(BaseModel):
    user_id: str
    subject_id: str | None = None
    items: list[KnowledgeMasteryItemResponse] = Field(default_factory=list)


class SessionResponse(BaseModel):
    id: str
    user_id: str
    subject_id: str
    title: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    latest_quiz: list[dict[str, Any]] = Field(default_factory=list)
    session_memory: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class LatestQuizResponse(BaseModel):
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
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
async def get_memory(
    user_id: str,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return get_memory_service(user_id)


@router.get("/users/{user_id}/knowledge/mastery", response_model=KnowledgeMasteryResponse)
async def get_knowledge_mastery(
    user_id: str,
    subject_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return get_knowledge_mastery_service(user_id, subject_id=subject_id, limit=limit)


@router.get("/users/{user_id}/profile", response_model=UserProfileResponse)
async def get_profile(
    user_id: str,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return get_profile_service(user_id)


@router.put("/users/{user_id}/profile", response_model=UserProfileResponse)
async def update_profile(
    user_id: str,
    body: UserProfileUpdateRequest,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return update_profile_service(
        user_id,
        {
            "display_name": body.display_name,
            "agent_style_name": body.agent_style_name,
            "agent_style_prompt": body.agent_style_prompt,
            "onboarding_completed": body.onboarding_completed,
        },
    )


@router.get("/users/{user_id}/sessions", response_model=list[SessionResponse])
async def get_sessions(
    user_id: str,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return get_sessions_service(user_id)


@router.delete("/users/{user_id}/sessions/{session_id}")
async def remove_session(
    user_id: str,
    session_id: str,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    try:
        return remove_session_service(user_id, session_id).model_dump()
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc


@router.get("/users/{user_id}/quiz/latest", response_model=LatestQuizResponse)
async def get_latest_quiz_for_user(
    user_id: str,
    _: AuthenticatedUser = Depends(verify_user_access),
):
    return get_latest_quiz_bundle_service(user_id)
