"""
Chat API — POST /chat
======================
接收用户问题，通过 LangGraph 工作流处理，以 SSE 流式返回结果。

SSE 事件类型：
  - routing      : 路由结果 { question_type }
  - retrieval    : 检索完成 { doc_count, is_rewritten }
  - explanation  : 讲解内容 { topic, thinking, steps, ... }
  - quiz         : 练习题 { items: [...] }
  - memory       : 记忆更新 { weak_points, ... }
  - explanation  : 元问题回答也复用 explanation 事件
  - done         : 处理完成
  - error        : 发生错误
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.application.chat.service import (
    run_chat_sync,
    stream_chat,
)
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.api.chat_presenter import event_name_for_node, extract_event_data
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()


# ---------- 请求 / 响应模型 ----------
class ChatRequest(BaseModel):
    """聊天请求体"""
    user_id: str = Field(..., description="用户唯一标识")
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="会话 ID，不传则自动生成",
    )
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    subject_id: str = Field(default=DEFAULT_SUBJECT_ID, description="知识库 ID，默认用于辅助参考")


class ChatResponse(BaseModel):
    """非流式响应"""
    session_id: str
    question_type: str
    route: str = "explain"
    explanation: dict
    quiz_items: list | None = None
    quiz_request: dict | None = None
    quiz_clarification: dict | None = None
    memory: dict | None = None


# ---------- 路由：SSE 流式 ----------
@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/chat — 接收用户问题，SSE 流式返回
    """
    if request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="不能使用其他用户身份发起请求")

    logger.info(f"💬 收到问题: user={request.user_id}, q={request.question[:50]}...")

    async def event_generator():
        stream_state: dict = {}
        try:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "message": "已连接学习引擎，正在判断问题类型。",
                        "session_id": request.session_id,
                    },
                    ensure_ascii=False,
                ),
            }

            async for chunk in stream_chat(
                user_id=request.user_id,
                session_id=request.session_id,
                question=request.question,
                subject_id=request.subject_id,
            ):
                node = chunk["node"]
                state_update = chunk["state_update"]
                elapsed = chunk["elapsed"]
                stream_state.update(state_update)

                event_name = event_name_for_node(node)
                event_state = dict(state_update)
                for field in (
                    "question_type",
                    "teaching_input_type",
                    "route",
                    "contextual_question",
                    "notebook_policy",
                    "search_policy",
                    "source_policy",
                    "learning_context",
                    "guard",
                    "allow_tools",
                    "allow_search",
                ):
                    if field not in event_state and field in stream_state:
                        event_state[field] = stream_state[field]
                if node == "quiz_output_node" and "quiz_items" not in event_state:
                    event_state["quiz_items"] = stream_state.get("quiz_items", [])
                event_data = extract_event_data(node, event_state)
                event_data["elapsed"] = elapsed

                yield {
                    "event": event_name,
                    "data": json.dumps(event_data, ensure_ascii=False),
                }

            # 流结束
            yield {
                "event": "done",
                "data": json.dumps({"message": "处理完成"}, ensure_ascii=False),
            }

        except asyncio.CancelledError:
            logger.info("💬 SSE 客户端已断开连接")
            raise
        except Exception as e:
            error_message = str(e).strip() or e.__class__.__name__
            logger.exception(f"❌ 工作流执行异常: {error_message}")
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": error_message,
                        "error_type": e.__class__.__name__,
                        "session_id": request.session_id,
                    },
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(event_generator(), ping=10)


# ---------- 路由：同步（调试用） ----------
@router.post("/chat/sync", response_model=ChatResponse)
async def chat_sync(
    request: ChatRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/chat/sync — 非流式版本，一次性返回全部结果
    """
    if request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="不能使用其他用户身份发起请求")

    logger.info(f"💬 [同步] 收到问题: {request.question[:50]}...")

    try:
        result = run_chat_sync(
            user_id=request.user_id,
            session_id=request.session_id,
            question=request.question,
            subject_id=request.subject_id,
        )

        return ChatResponse(
            session_id=request.session_id,
            question_type=result.question_type,
            route=result.route,
            explanation=result.explanation.model_dump(),
            quiz_items=[item.model_dump() for item in result.quiz_items],
            quiz_request=result.quiz_request.model_dump() if result.quiz_request else None,
            quiz_clarification=result.quiz_clarification.model_dump() if result.quiz_clarification else None,
            memory=result.memory.model_dump(),
        )

    except Exception as e:
        logger.error(f"❌ 同步工作流执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
