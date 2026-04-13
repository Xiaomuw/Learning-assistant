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

import json
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from db.repositories import append_chat_turn, get_subject_by_id, get_user_profile
from schemas.state import AgentState
from graph.workflow import run_workflow, stream_workflow
from agents.memory import _load_memory

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
    subject_id: str = Field(default="general", description="学科 ID，默认为通用")


class ChatResponse(BaseModel):
    """非流式响应"""
    session_id: str
    question_type: str
    explanation: dict
    quiz_items: list | None = None
    memory: dict | None = None


# ---------- SSE 事件映射 ----------

# LangGraph 节点名 → SSE 事件名 + 提取的 state 字段
NODE_EVENT_MAP: dict[str, dict[str, Any]] = {
    "router": {
        "event": "routing",
        "fields": ["question_type"],
    },
    "retriever": {
        "event": "retrieval",
        "fields": ["retrieved_docs", "is_rewritten"],
    },
    "explain_node": {
        "event": "explanation",
        "fields": ["explanation"],
    },
    "quiz_gen": {
        "event": "quiz",
        "fields": ["quiz_items", "final_answer"],
    },
    "memory_node": {
        "event": "memory",
        "fields": ["memory"],
    },
    "meta_node": {
        "event": "explanation",
        "fields": ["explanation", "final_answer"],
    },
}


def _extract_event_data(node: str, state_update: dict[str, Any]) -> dict[str, Any]:
    """从节点的 state_update 中提取 SSE 需要的字段"""
    mapping = NODE_EVENT_MAP.get(node, {})
    fields = mapping.get("fields", [])

    data: dict[str, Any] = {}
    for field in fields:
        if field in state_update:
            value = state_update[field]
            # 特殊处理：retrieval 只返回文档数量，不返回全文
            if field == "retrieved_docs" and isinstance(value, list):
                data["doc_count"] = len(value)
                data["top_scores"] = [
                    round(d.get("score", 0), 2) for d in value[:3]
                ]
            else:
                data[field] = value
    return data


# ---------- 构建初始 State ----------

def _build_initial_state(request: ChatRequest) -> AgentState:
    """构建初始 AgentState，包含从持久化加载的用户记忆"""
    # 加载已有记忆
    existing_memory = _load_memory(request.user_id)
    user_profile = get_user_profile(request.user_id)

    subject = get_subject_by_id(request.subject_id)
    subject_name = subject["name"] if subject else "通用知识"
    subject_description = subject.get("description", "") if subject else ""

    initial_state: AgentState = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "subject_id": request.subject_id,
        "subject_name": subject_name,
        "subject_description": subject_description,
        "question": request.question,
        "memory": existing_memory,
        "user_style_name": user_profile.get("agent_style_name", ""),
        "user_style_prompt": user_profile.get("agent_style_prompt", ""),
    }

    logger.info(
        f"📋 初始 State 构建完成 | user={request.user_id} | "
        f"subject={subject_name} | "
        f"memory_loaded={bool(existing_memory.get('recent_topics'))}"
    )
    return initial_state


def _build_assistant_message(final_state: dict[str, Any]) -> dict[str, Any]:
    explanation = final_state.get("explanation") or {}
    quiz_items = final_state.get("quiz_items") or []
    content = (
        explanation.get("thinking")
        or final_state.get("final_answer")
        or ("我已经帮你准备好一组练习题。" if quiz_items else "这轮学习已经处理完成。")
    )

    message = {
        "role": "assistant",
        "content": content,
        "timestamp": int(time.time() * 1000),
    }

    if explanation:
        message["explanation"] = explanation
    if quiz_items:
        message["quiz"] = quiz_items

    return message


def _persist_chat_session(request: ChatRequest, final_state: dict[str, Any]) -> None:
    user_message = {
        "role": "user",
        "content": request.question,
        "timestamp": int(time.time() * 1000) - 1,
    }
    assistant_message = _build_assistant_message(final_state)

    append_chat_turn(
        user_id=request.user_id,
        session_id=request.session_id,
        subject_id=request.subject_id,
        title=request.question[:50] or "新对话",
        user_message=user_message,
        assistant_message=assistant_message,
        latest_quiz=final_state.get("quiz_items") or [],
    )


# ---------- 路由：SSE 流式 ----------
@router.post("/chat")
async def chat(request: ChatRequest):
    """
    POST /api/chat — 接收用户问题，SSE 流式返回
    """
    logger.info(f"💬 收到问题: user={request.user_id}, q={request.question[:50]}...")

    initial_state = _build_initial_state(request)

    async def event_generator():
        final_state: dict[str, Any] = dict(initial_state)
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

            async for chunk in stream_workflow(initial_state):
                node = chunk["node"]
                state_update = chunk["state_update"]
                elapsed = chunk["elapsed"]
                final_state.update(state_update)

                mapping = NODE_EVENT_MAP.get(node, {})
                event_name = mapping.get("event", node)
                event_data = _extract_event_data(node, state_update)
                event_data["elapsed"] = elapsed

                yield {
                    "event": event_name,
                    "data": json.dumps(event_data, ensure_ascii=False),
                }

            _persist_chat_session(request, final_state)

            # 流结束
            yield {
                "event": "done",
                "data": json.dumps({"message": "处理完成"}, ensure_ascii=False),
            }

        except Exception as e:
            logger.error(f"❌ 工作流执行异常: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator(), ping=10)


# ---------- 路由：同步（调试用） ----------
@router.post("/chat/sync", response_model=ChatResponse)
async def chat_sync(request: ChatRequest):
    """
    POST /api/chat/sync — 非流式版本，一次性返回全部结果
    """
    logger.info(f"💬 [同步] 收到问题: {request.question[:50]}...")

    initial_state = _build_initial_state(request)

    try:
        final_state = run_workflow(initial_state)
        _persist_chat_session(request, final_state)

        return ChatResponse(
            session_id=request.session_id,
            question_type=final_state.get("question_type", "concept"),
            explanation=final_state.get("explanation", {}),
            quiz_items=final_state.get("quiz_items"),
            memory=final_state.get("memory"),
        )

    except Exception as e:
        logger.error(f"❌ 同步工作流执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
