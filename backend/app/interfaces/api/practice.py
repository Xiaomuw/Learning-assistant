"""
Practice API
============
练习推荐与做题记录接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from app.application.practice.pack_service import create_pack_from_request
from app.application.practice.service import get_recommendations, submit_attempt
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user, verify_user_access
from app.shared.schemas.contracts import PracticeRecommendation
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()


class PracticeRecommendationsResponse(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    items: list[dict[str, Any]] = Field(default_factory=list)


class PracticeAttemptRequest(BaseModel):
    user_id: str
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    quiz_item: PracticeRecommendation
    selected_option: str = Field(min_length=1, max_length=1)


class PracticeAttemptResponse(BaseModel):
    is_correct: bool
    selected_option: str = ""
    correct_option: str
    explanation: str
    option_rationales: dict[str, str] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    session_memory: dict[str, Any] | None = None
    mastery_evaluation: dict[str, Any] | None = None
    personalized_feedback: str = ""


class PracticePackRequest(BaseModel):
    user_id: str
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    request_text: str = Field(default="AI补题", min_length=1, max_length=500)
    current_practice_question: dict[str, Any] | None = None
    last_practice_pack: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class PracticePackResponse(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    quiz_request: dict[str, Any]
    quiz_clarification: dict[str, Any] | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/users/{user_id}/practice/recommendations", response_model=PracticeRecommendationsResponse)
async def get_practice_recommendations(
    user_id: str,
    subject_id: str | None = Query(default=None),
    limit: int = Query(default=4, ge=1, le=8),
    _: AuthenticatedUser = Depends(verify_user_access),
):
    result = get_recommendations(user_id=user_id, subject_id=subject_id, limit=limit)
    return {
        "subject_id": result.subject_id,
        "items": [item.model_dump() for item in result.items],
    }


@router.post("/practice/attempts", response_model=PracticeAttemptResponse)
async def submit_practice_attempt(
    body: PracticeAttemptRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    if body.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="不能写入其他用户的做题记录")

    try:
        result = submit_attempt(
            user_id=body.user_id,
            session_id=body.session_id,
            subject_id=body.subject_id,
            quiz_item=body.quiz_item,
            selected_option=body.selected_option,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or "这道题的数据格式不完整，请重新生成题包后再作答。",
        ) from exc
    except Exception as exc:
        logger.exception("提交做题记录失败")
        raise HTTPException(
            status_code=500,
            detail=(
                "提交作答失败：服务端暂时无法保存这次做题记录。"
                "请保留当前页面稍后重试，或重新生成一组题包。"
            ),
        ) from exc
    return {
        "is_correct": result.is_correct,
        "selected_option": result.selected_option or body.selected_option.strip().upper()[:1],
        "correct_option": result.correct_option,
        "explanation": result.explanation,
        "option_rationales": result.option_rationales,
        "memory": result.memory.model_dump(),
        "session_memory": result.session_memory,
        "mastery_evaluation": result.mastery_evaluation.model_dump() if result.mastery_evaluation else None,
        "personalized_feedback": result.personalized_feedback,
    }


@router.post("/practice/packs", response_model=PracticePackResponse)
async def create_practice_pack(
    body: PracticePackRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    if body.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="不能为其他用户生成题包")

    result = create_pack_from_request(
        user_id=body.user_id,
        session_id=body.session_id,
        subject_id=body.subject_id,
        request_text=body.request_text,
        current_practice_question=body.current_practice_question,
        last_practice_pack=body.last_practice_pack,
        context=body.context,
    )
    return {
        "subject_id": result.subject_id,
        "quiz_request": result.quiz_request.model_dump(mode="json"),
        "quiz_clarification": result.quiz_clarification.model_dump(mode="json") if result.quiz_clarification else None,
        "items": [item.model_dump() for item in result.items],
    }
