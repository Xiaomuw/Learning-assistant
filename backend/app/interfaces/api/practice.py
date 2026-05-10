"""
Practice API
============
练习推荐与做题记录接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import DataError, IntegrityError, StatementError

from app.application.practice.pack_service import create_pack_from_request
from app.application.practice.service import get_recommendations, submit_attempt
from app.infrastructure.llm.langsmith import trace_run
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user, verify_user_access
from app.shared.schemas.contracts import PracticeRecommendation
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()

PRACTICE_ATTEMPT_CONSTRAINT_DETAIL = (
    "题目数据包含过长或不合法字段，请重新生成题包后再作答。"
)
PRACTICE_OPTION_KEYS = ("A", "B", "C", "D")


class PracticeRecommendationsResponse(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    items: list[dict[str, Any]] = Field(default_factory=list)


class PracticeAttemptRequest(BaseModel):
    user_id: str
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    quiz_item: PracticeRecommendation
    selected_option: str = Field(min_length=1, max_length=1)

    @field_validator("selected_option", mode="before")
    @classmethod
    def normalize_selected_option(cls, value: Any) -> str:
        option = str(value or "").strip().upper()
        if option not in PRACTICE_OPTION_KEYS:
            raise ValueError("selected_option 必须是 A/B/C/D")
        return option

    @model_validator(mode="after")
    def normalize_quiz_item_for_submission(self) -> "PracticeAttemptRequest":
        question = str(self.quiz_item.question or "").strip()
        if not question:
            raise ValueError("quiz_item.question 不能为空")

        option_map: dict[str, str] = {}
        for option in self.quiz_item.options or []:
            key = str(option.get("key") or "").strip().upper()[:1]
            text = str(option.get("text") or "").strip()
            if key in PRACTICE_OPTION_KEYS and text:
                option_map[key] = text

        if set(option_map) != set(PRACTICE_OPTION_KEYS):
            raise ValueError("quiz_item.options 必须完整包含 A/B/C/D 四个选项")

        correct_option = str(self.quiz_item.correct_option or "").strip().upper()[:1]
        if correct_option not in PRACTICE_OPTION_KEYS:
            raise ValueError("quiz_item.correct_option 必须是 A/B/C/D")

        self.quiz_item = self.quiz_item.model_copy(
            update={
                "question": question,
                "options": [{"key": key, "text": option_map[key]} for key in PRACTICE_OPTION_KEYS],
                "correct_option": correct_option,
            }
        )
        return self


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
    generation_status: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""


def _is_practice_attempt_constraint_error(exc: Exception) -> bool:
    if isinstance(exc, (DataError, IntegrityError, StatementError)):
        return True

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "value too long",
            "character varying",
            "violates check constraint",
            "violates not-null constraint",
            "violates foreign key constraint",
            "violates unique constraint",
        )
    )


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
        with trace_run(
            name="practice.attempt.submit",
            run_type="chain",
            inputs={
                "user_id": body.user_id,
                "session_id": body.session_id,
                "subject_id": body.subject_id,
                "question": body.quiz_item.question,
                "selected_option": body.selected_option,
                "quiz_item": body.quiz_item.model_dump(mode="json"),
            },
            metadata={
                "component": "PracticeAttempt",
                "subject_id": body.subject_id,
                "session_id": body.session_id,
                "source_type": body.quiz_item.source_type,
            },
            tags=["learning-assistant", "practice", "attempt"],
        ) as run:
            result = submit_attempt(
                user_id=body.user_id,
                session_id=body.session_id,
                subject_id=body.subject_id,
                quiz_item=body.quiz_item,
                selected_option=body.selected_option,
            )
            run.end(
                outputs={
                    "is_correct": result.is_correct,
                    "selected_option": result.selected_option or body.selected_option.strip().upper()[:1],
                    "correct_option": result.correct_option,
                    "explanation": result.explanation,
                    "knowledge_point": body.quiz_item.knowledge_point,
                    "mastery_evaluation": result.mastery_evaluation.model_dump(mode="json") if result.mastery_evaluation else None,
                }
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or "这道题的数据格式不完整，请重新生成题包后再作答。",
        ) from exc
    except (DataError, IntegrityError, StatementError) as exc:
        logger.warning("提交做题记录被数据库约束拒绝: {}", exc.__class__.__name__)
        raise HTTPException(
            status_code=400,
            detail=PRACTICE_ATTEMPT_CONSTRAINT_DETAIL,
        ) from exc
    except RuntimeError as exc:
        if _is_practice_attempt_constraint_error(exc):
            logger.warning("提交做题记录被约束类错误拒绝: {}", exc.__class__.__name__)
            raise HTTPException(
                status_code=400,
                detail=PRACTICE_ATTEMPT_CONSTRAINT_DETAIL,
            ) from exc
        logger.exception("提交做题记录失败")
        raise HTTPException(
            status_code=500,
            detail=(
                "提交作答失败：服务端暂时无法保存这次做题记录。"
                "请保留当前页面稍后重试，或重新生成一组题包。"
            ),
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

    with trace_run(
        name="practice.pack.create",
        run_type="chain",
        inputs={
            "user_id": body.user_id,
            "session_id": body.session_id,
            "subject_id": body.subject_id,
            "request_text": body.request_text,
            "current_practice_question": body.current_practice_question or {},
            "last_practice_pack_count": len(body.last_practice_pack),
            "context": body.context,
        },
        metadata={
            "component": "PracticePack",
            "subject_id": body.subject_id,
            "session_id": body.session_id,
        },
        tags=["learning-assistant", "practice", "pack"],
    ) as run:
        result = create_pack_from_request(
            user_id=body.user_id,
            session_id=body.session_id,
            subject_id=body.subject_id,
            request_text=body.request_text,
            current_practice_question=body.current_practice_question,
            last_practice_pack=body.last_practice_pack,
            context=body.context,
        )
        run.end(
            outputs={
                "subject_id": result.subject_id,
                "item_count": len(result.items),
                "message": result.message,
                "quiz_request": result.quiz_request.model_dump(mode="json"),
                "generation_status": dict(result.generation_status or {}),
                "error_count": len(result.errors or []),
            }
        )
    return {
        "subject_id": result.subject_id,
        "quiz_request": result.quiz_request.model_dump(mode="json"),
        "quiz_clarification": result.quiz_clarification.model_dump(mode="json") if result.quiz_clarification else None,
        "items": [item.model_dump() for item in result.items],
        "generation_status": dict(result.generation_status or {}),
        "errors": list(result.errors or []),
        "message": result.message,
    }
