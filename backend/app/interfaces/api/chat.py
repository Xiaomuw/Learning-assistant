"""
Chat API — POST /chat
======================
接收用户问题，通过 LangGraph 工作流处理，以 SSE 流式返回结果。

SSE 事件类型：
  - routing      : 路由结果 { question_type }
  - retrieval    : 检索完成 { doc_count, is_rewritten }
  - reasoning_delta : 思考模式调试流 { delta, ephemeral }
  - answer_delta : 回答正文流 { delta }
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
import hashlib
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.application.chat.service import (
    run_chat_once,
    stream_chat,
)
from app.infrastructure.db.repositories.chat_jobs import (
    create_chat_async_job,
    get_chat_async_job,
    mark_chat_async_job_completed,
    mark_chat_async_job_failed,
)
from app.infrastructure.llm.config import (
    get_chat_sync_inline_budget_seconds,
    get_chat_sync_poll_retry_after_ms,
)
from app.infrastructure.observability.request_context import get_request_id, reset_request_id, set_request_id
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.api.chat_presenter import event_name_for_node, extract_event_data
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()

CHAT_HEARTBEAT_SECONDS = 12.0
_RUNNING_CHAT_JOBS: dict[str, asyncio.Task] = {}


def _runtime_stream_sse_event(raw_event: Any, *, session_id: str) -> dict[str, str] | None:
    if not isinstance(raw_event, dict):
        return None
    event_name = str(raw_event.get("event") or "").strip()
    raw_data = raw_event.get("data") if isinstance(raw_event.get("data"), dict) else {}
    if event_name == "answer_delta":
        delta = str(raw_data.get("delta") or "")
        streaming_mode = str(raw_data.get("streaming_mode") or "token")
        is_synthetic_delta = bool(raw_data.get("is_synthetic_delta", False))
        if not delta or streaming_mode != "token" or is_synthetic_delta:
            return None
        data = {
            "delta": delta,
            "streaming_mode": streaming_mode,
            "is_synthetic_delta": False,
            "session_id": session_id,
        }
    elif event_name == "status":
        data = {
            "stream_stage": str(raw_data.get("stream_stage") or "model_progress"),
            "stage_label": str(raw_data.get("stage_label") or "实时进度"),
            "detail": str(raw_data.get("detail") or ""),
            "safe_decision_summary": str(raw_data.get("safe_decision_summary") or ""),
            "status": str(raw_data.get("status") or "running"),
            "streaming_mode": str(raw_data.get("streaming_mode") or "token"),
            "session_id": session_id,
        }
        reasoning_trace_char_count = int(raw_data.get("reasoning_trace_char_count") or 0)
        if reasoning_trace_char_count > 0:
            data["reasoning_trace_char_count"] = reasoning_trace_char_count
    else:
        return None
    return {"event": event_name, "data": json.dumps(data, ensure_ascii=False)}


async def _cancel_task_safely(task: asyncio.Task | None) -> None:
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _safe_chat_error_message(exc: Exception) -> str:
    reason = _chat_error_reason(exc)
    if reason == "timeout":
        return "模型响应超时，我已停止本轮处理。请稍后重试，或把问题拆小后再问。"
    if reason == "model_unavailable":
        return "当前模型服务暂时不可用，我没有拿到稳定回答。请稍后重试，或切换模型后再问。"
    return "模型暂时无法完成本轮处理，我已安全停止。请稍后重试，或换一种问法继续。"


def _safe_chat_error_type(exc: Exception) -> str:
    return _chat_error_reason(exc)


def _chat_error_reason(exc: Exception) -> str:
    text = f"{exc.__class__.__name__} {str(exc)}".lower()
    if any(marker in text for marker in ("timeout", "timed out", "超时")):
        return "timeout"
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "429",
            "unauthorized",
            "forbidden",
            "api connection",
            "api status",
            "connection error",
            "connection refused",
            "dns",
            "inference.do-ai.run",
            "model not found",
            "model unavailable",
            "not available",
            "rate limit",
            "subscription tier",
            "temporary failure in name resolution",
        )
    ):
        return "model_unavailable"
    return "workflow_error"


def _question_log_metadata(question: str) -> dict[str, str | int]:
    normalized = " ".join((question or "").split())
    return {
        "question_len": len(question or ""),
        "question_preview": normalized[:30],
        "question_hash": hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:16],
    }


def _chat_sync_timeout_response(*, session_id: str) -> ChatResponse:
    final_answer = (
        "云端模型响应超过本轮同步预算，我先安全返回，避免手机端连接超时。"
        "请稍后重试，或把问题拆成更具体的小问题继续问。"
    )
    return ChatResponse(
        session_id=session_id,
        question_type="concept",
        route="explain",
        final_answer=final_answer,
        explanation={
            "topic": "云端响应较慢",
            "thinking": "本轮同步聊天超过预算，已触发快速降级保护。",
            "steps": [
                "后端服务仍在线，但模型或外部工具响应较慢。",
                "系统已停止等待本轮长响应，避免小程序 callContainer 先超时。",
                "稍后重试时会继续优先使用知识库与联网搜索补充回答。",
            ],
            "mistakes": "",
            "similar": [],
        },
        quiz_items=[],
        memory={
            "weak_points": [],
            "error_count": {},
            "recent_topics": [],
            "last_session": "",
        },
    )


def _chat_response_from_result(
    *,
    body: ChatRequest,
    result,
    request_id: str,
    job_id: str | None = None,
) -> ChatResponse:
    return ChatResponse(
        session_id=body.session_id,
        question_type=result.question_type,
        route=result.route,
        final_answer=result.final_answer,
        explanation=result.explanation.model_dump(),
        quiz_items=[item.model_dump() for item in result.quiz_items],
        quiz_request=result.quiz_request.model_dump() if result.quiz_request else None,
        quiz_clarification=result.quiz_clarification.model_dump() if result.quiz_clarification else None,
        memory=result.memory.model_dump(),
        status="completed",
        job_id=job_id,
        request_id=request_id,
    )


def _chat_sync_pending_response(*, session_id: str, job_id: str, request_id: str) -> ChatResponse:
    retry_after_ms = get_chat_sync_poll_retry_after_ms()
    return ChatResponse(
        session_id=session_id,
        question_type="concept",
        route="explain",
        final_answer="我正在联网搜索并整理答案，稍等一下就好。",
        explanation={
            "topic": "正在整理答案",
            "thinking": "本轮需要联网搜索或较长模型生成，已转入后台继续处理。",
            "steps": [
                "先返回 pending，避免手机端 callContainer 超时。",
                "后台会继续完成知识库检索、联网搜索和答案整理。",
                "小程序会自动轮询，完成后替换为最终回答。",
            ],
            "mistakes": "",
            "similar": [],
        },
        quiz_items=[],
        memory={
            "weak_points": [],
            "error_count": {},
            "recent_topics": [],
            "last_session": "",
        },
        status="pending",
        job_id=job_id,
        request_id=request_id,
        retry_after_ms=retry_after_ms,
    )


def _chat_response_to_job_result(response: ChatResponse) -> dict[str, Any]:
    return response.model_dump(mode="json")


def _job_error_payload(exc: Exception, *, request_id: str) -> dict[str, Any]:
    reason = _chat_error_reason(exc)
    return {
        "error": _safe_chat_error_message(exc),
        "reason": reason,
        "retryable": reason in {"timeout", "model_unavailable", "workflow_error"},
        "request_id": request_id,
    }


async def _run_chat_async_job(*, job_id: str, body: ChatRequest, request_id: str) -> ChatResponse | None:
    token = set_request_id(request_id)
    started_at = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            run_chat_once,
            user_id=body.user_id,
            session_id=body.session_id,
            question=body.question,
            subject_id=body.subject_id,
            thinking_mode=body.thinking_mode,
            client_request_id=body.client_request_id,
            request_id=request_id,
        )
        response = _chat_response_from_result(body=body, result=result, request_id=request_id, job_id=job_id)
        mark_chat_async_job_completed(job_id=job_id, result=_chat_response_to_job_result(response))
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "✅ [同步后台] 问答任务完成: request_id={} job_id={} status=completed elapsed_ms={}",
            request_id,
            job_id,
            elapsed_ms,
        )
        return response
    except Exception as exc:  # noqa: BLE001 - background job should persist structured failure
        error_payload = _job_error_payload(exc, request_id=request_id)
        mark_chat_async_job_failed(job_id=job_id, error=error_payload)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error(
            "❌ [同步后台] 问答任务失败: request_id={} job_id={} reason={} elapsed_ms={} error={}",
            request_id,
            job_id,
            error_payload.get("reason"),
            elapsed_ms,
            error_payload.get("error"),
        )
        return None
    finally:
        reset_request_id(token)


def _ensure_chat_job_task(*, job_id: str, body: ChatRequest, request_id: str) -> asyncio.Task:
    task = _RUNNING_CHAT_JOBS.get(job_id)
    if task and not task.done():
        return task
    task = asyncio.create_task(_run_chat_async_job(job_id=job_id, body=body, request_id=request_id))
    _RUNNING_CHAT_JOBS[job_id] = task
    task.add_done_callback(lambda _task: _RUNNING_CHAT_JOBS.pop(job_id, None))
    return task


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
    client_request_id: str | None = Field(
        default=None,
        max_length=160,
        description="可选客户端请求幂等 ID；同一值会复用本轮 message_id。",
    )


class ChatResponse(BaseModel):
    """非流式响应"""
    session_id: str
    question_type: str
    route: str = "explain"
    final_answer: str = ""
    explanation: dict
    quiz_items: list | None = None
    quiz_request: dict | None = None
    quiz_clarification: dict | None = None
    memory: dict | None = None
    status: str = "completed"
    job_id: str | None = None
    request_id: str | None = None
    retry_after_ms: int | None = None


class ChatJobResponse(BaseModel):
    """异步聊天任务查询响应"""
    status: str
    job_id: str
    request_id: str
    response: ChatResponse | None = None
    error: dict | None = None
    retryable: bool = True
    retry_after_ms: int = 2000


def _chat_job_response_from_row(*, job_id: str, job: dict[str, Any]) -> ChatJobResponse:
    status = str(job.get("status") or "pending")
    request_id = str(job.get("request_id") or job_id)
    if status == "completed" and job.get("result_json"):
        response = ChatResponse.model_validate(job["result_json"])
        return ChatJobResponse(
            status="completed",
            job_id=job_id,
            request_id=request_id,
            response=response,
            retryable=False,
            retry_after_ms=get_chat_sync_poll_retry_after_ms(),
        )

    if status == "failed":
        error_payload = dict(job.get("error_json") or {})
        return ChatJobResponse(
            status="failed",
            job_id=job_id,
            request_id=request_id,
            error=error_payload,
            retryable=bool(error_payload.get("retryable", True)),
            retry_after_ms=get_chat_sync_poll_retry_after_ms(),
        )

    return ChatJobResponse(
        status="pending",
        job_id=job_id,
        request_id=request_id,
        retryable=True,
        retry_after_ms=get_chat_sync_poll_retry_after_ms(),
    )


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
        pending_runtime_task: asyncio.Task | None = None
        runtime_stream_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def runtime_stream_writer(raw_event: dict[str, Any]) -> None:
            event = _runtime_stream_sse_event(raw_event, session_id=request.session_id)
            if event is None:
                return
            try:
                loop.call_soon_threadsafe(runtime_stream_queue.put_nowait, event)
            except RuntimeError:
                return

        try:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "message": "已接入模型，正在判断问题类型。",
                        "session_id": request.session_id,
                        "thinking_mode": request.thinking_mode,
                        "safe_decision_summary": (
                            "思考模式已启用：调试面板会临时显示本轮模型原始思考流；不会写入历史或 LangSmith。"
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
                client_request_id=request.client_request_id,
                stream_writer=runtime_stream_writer,
            )
            pending_chunk_task = asyncio.create_task(anext(chat_stream))
            pending_runtime_task = asyncio.create_task(runtime_stream_queue.get())
            heartbeat_count = 0

            while True:
                wait_tasks = {pending_chunk_task}
                if pending_runtime_task is not None:
                    wait_tasks.add(pending_runtime_task)
                done, _pending = await asyncio.wait(
                    wait_tasks,
                    timeout=CHAT_HEARTBEAT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
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

                if pending_runtime_task in done:
                    yield pending_runtime_task.result()
                    while not runtime_stream_queue.empty():
                        yield runtime_stream_queue.get_nowait()
                    pending_runtime_task = asyncio.create_task(runtime_stream_queue.get())

                if pending_chunk_task not in done:
                    continue

                try:
                    chunk = pending_chunk_task.result()
                except StopAsyncIteration:
                    await _cancel_task_safely(pending_runtime_task)
                    pending_runtime_task = None
                    while not runtime_stream_queue.empty():
                        yield runtime_stream_queue.get_nowait()
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
            await _cancel_task_safely(pending_runtime_task)
            raise
        except Exception as e:
            await _close_chat_stream_safely(
                chat_stream=chat_stream,
                pending_chunk_task=pending_chunk_task,
            )
            await _cancel_task_safely(pending_runtime_task)
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
                        "error_type": _safe_chat_error_type(e),
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
    body: ChatRequest,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/chat/sync — 非流式版本，一次性返回全部结果
    """
    if body.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="不能使用其他用户身份发起请求")

    request_id = get_request_id() or getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
    started_at = time.perf_counter()
    question_meta = _question_log_metadata(body.question)
    logger.info(
        "💬 [同步] 收到问题: request_id={} user={} session={} subject={} "
        "question_len={} question_preview={} question_hash={}",
        request_id,
        body.user_id,
        body.session_id,
        body.subject_id,
        question_meta["question_len"],
        question_meta["question_preview"],
        question_meta["question_hash"],
    )

    job_id = request_id
    existing_job = get_chat_async_job(user_id=body.user_id, job_id=job_id)
    if existing_job and existing_job.get("status") == "completed" and existing_job.get("result_json"):
        return ChatResponse.model_validate(existing_job["result_json"])
    if existing_job and existing_job.get("status") == "failed" and existing_job.get("error_json"):
        error_payload = dict(existing_job["error_json"] or {})
        return JSONResponse(status_code=500, content=error_payload)

    create_chat_async_job(
        job_id=job_id,
        user_id=body.user_id,
        session_id=body.session_id,
        request_id=request_id,
    )
    task = _ensure_chat_job_task(job_id=job_id, body=body, request_id=request_id)

    try:
        inline_budget_seconds = get_chat_sync_inline_budget_seconds()
        response = await asyncio.wait_for(asyncio.shield(task), timeout=inline_budget_seconds)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if response is None:
            job = get_chat_async_job(user_id=body.user_id, job_id=job_id)
            error_payload = dict((job or {}).get("error_json") or _job_error_payload(RuntimeError("workflow_error"), request_id=request_id))
            return JSONResponse(status_code=500, content=error_payload)
        logger.info(
            "✅ [同步] 问答完成: request_id={} route={} question_type={} elapsed_ms={}",
            request_id,
            response.route,
            response.question_type,
            elapsed_ms,
        )
        return response

    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "⏳ [同步] 问答超过内联预算，返回 pending: request_id={} job_id={} inline_budget_seconds={} elapsed_ms={}",
            request_id,
            job_id,
            get_chat_sync_inline_budget_seconds(),
            elapsed_ms,
        )
        return _chat_sync_pending_response(session_id=body.session_id, job_id=job_id, request_id=request_id)

    except Exception as e:
        error_message = _safe_chat_error_message(e)
        reason = _chat_error_reason(e)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error(
            "❌ [同步] 工作流执行失败: request_id={} reason={} elapsed_ms={} error={}",
            request_id,
            reason,
            elapsed_ms,
            error_message,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": error_message,
                "reason": reason,
                "retryable": reason in {"timeout", "model_unavailable", "workflow_error"},
                "request_id": request_id,
            },
        )


@router.get("/chat/jobs/{job_id}", response_model=ChatJobResponse)
async def get_chat_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    GET /api/chat/jobs/{job_id} — 查询同步聊天后台任务结果
    """
    job = get_chat_async_job(user_id=current_user.id, job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="聊天任务不存在")

    response = _chat_job_response_from_row(job_id=job_id, job=job)
    logger.info(
        "🔎 [同步后台] 查询任务: request_id={} job_id={} status={} method=GET",
        response.request_id,
        job_id,
        response.status,
    )
    return response


@router.post("/chat/jobs/{job_id}/poll", response_model=ChatJobResponse)
async def poll_chat_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/chat/jobs/{job_id}/poll — 小程序云托管轮询后台聊天任务结果
    """
    job = get_chat_async_job(user_id=current_user.id, job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="聊天任务不存在")

    response = _chat_job_response_from_row(job_id=job_id, job=job)
    logger.info(
        "🔎 [同步后台] 查询任务: request_id={} job_id={} status={} method=POST",
        response.request_id,
        job_id,
        response.status,
    )
    return response
