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
import contextlib
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

CHAT_HEARTBEAT_SECONDS = 12.0


def _safe_chat_error_message(exc: Exception) -> str:
    raw_message = str(exc).strip()
    if raw_message:
        return raw_message
    if exc.__class__.__name__ and exc.__class__.__name__ != "Exception":
        return f"学习引擎处理失败（{exc.__class__.__name__}），请稍后重试。"
    return "学习引擎处理失败，请稍后重试。"


def _chat_error_reason(exc: Exception) -> str:
    text = f"{exc.__class__.__name__} {str(exc)}".lower()
    if any(marker in text for marker in ("timeout", "timed out", "超时")):
        return "timeout"
    if any(
        marker in text
        for marker in (
            "api connection",
            "connection error",
            "connection refused",
            "dns",
            "inference.do-ai.run",
            "model not found",
            "model unavailable",
            "temporary failure in name resolution",
        )
    ):
        return "model_unavailable"
    return "workflow_error"


async def _close_chat_stream_safely(
    *,
    chat_stream,
    pending_chunk_task: asyncio.Task | None,
) -> None:
    if pending_chunk_task and not pending_chunk_task.done():
        pending_chunk_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending_chunk_task

    if chat_stream is None:
        return

    try:
        await chat_stream.aclose()
    except RuntimeError as exc:
        message = str(exc).lower()
        if "aclose" in message and "running" in message:
            logger.debug("SSE stream close skipped because async generator is already closing")
            return
        logger.warning(f"⚠️ SSE stream close failed: {exc}")
    except asyncio.CancelledError:
        logger.debug("SSE stream close was cancelled by client disconnect")
    except Exception as exc:  # pragma: no cover - defensive cleanup guard
        logger.warning(f"⚠️ SSE stream close failed: {exc}")


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
    thinking_mode: bool = Field(default=False, description="是否为本轮 DeepSeek V4 请求启用思考模式")


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
        chat_stream = None
        pending_chunk_task: asyncio.Task | None = None
        try:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "message": "已连接学习引擎，正在判断问题类型。",
                        "session_id": request.session_id,
                        "thinking_mode": request.thinking_mode,
                        "safe_decision_summary": (
                            "思考模式已启用：后端会请求模型进行更充分推理，但界面只展示安全摘要和最终回答。"
                            if request.thinking_mode
                            else ""
                        ),
                    },
                    ensure_ascii=False,
                ),
            }

            chat_stream = stream_chat(
                user_id=request.user_id,
                session_id=request.session_id,
                question=request.question,
                subject_id=request.subject_id,
                thinking_mode=request.thinking_mode,
            )
            pending_chunk_task = asyncio.create_task(anext(chat_stream))
            heartbeat_count = 0

            while True:
                done, _pending = await asyncio.wait(
                    {pending_chunk_task},
                    timeout=CHAT_HEARTBEAT_SECONDS,
                )
                if not done:
                    heartbeat_count += 1
                    yield {
                        "event": "status",
                        "data": json.dumps(
                            {
                                "message": "仍在处理，本轮可能需要更久。",
                                "heartbeat": True,
                                "heartbeat_count": heartbeat_count,
                                "session_id": request.session_id,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    continue

                try:
                    chunk = pending_chunk_task.result()
                except StopAsyncIteration:
                    break

                pending_chunk_task = asyncio.create_task(anext(chat_stream))
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
            await _close_chat_stream_safely(
                chat_stream=chat_stream,
                pending_chunk_task=pending_chunk_task,
            )
            raise
        except Exception as e:
            await _close_chat_stream_safely(
                chat_stream=chat_stream,
                pending_chunk_task=pending_chunk_task,
            )
            error_message = _safe_chat_error_message(e)
            reason = _chat_error_reason(e)
            if reason in {"timeout", "model_unavailable"}:
                logger.warning(f"⚠️ 工作流执行中断: reason={reason} error={error_message}")
            else:
                logger.warning(f"❌ 工作流执行异常: reason={reason} error={error_message}")
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": error_message,
                        "error_type": e.__class__.__name__,
                        "reason": reason,
                        "retryable": True,
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
            thinking_mode=request.thinking_mode,
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
        error_message = _safe_chat_error_message(e)
        logger.error(f"❌ 同步工作流执行失败: {error_message}")
        raise HTTPException(status_code=500, detail=f"处理失败: {error_message}")
