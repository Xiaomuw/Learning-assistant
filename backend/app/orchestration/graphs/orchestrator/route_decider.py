from __future__ import annotations

import os
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.domains.practice.quiz_request import resolve_quiz_request
from app.domains.qa.lightweight_intent import classify_lightweight_answer_intent
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.qa.fact_boundary import (
    QUESTION_META_TOOL_USAGE,
    QUESTION_REALTIME_OR_FRESH,
    classify_question_boundary,
)
from app.orchestration.graphs.shared.schemas import GraphType, SourcePolicy, ToolCapability, ToolStatus
from app.shared.schemas.contracts import QuizRequestResolution


class BoundaryRoute(StrEnum):
    SIMPLE_FACT = "simple_fact"
    PRACTICE_GENERATION = "practice_generation"
    META_TOOL_USAGE = "meta_tool_usage"
    REALTIME_OR_FRESH = "realtime_or_fresh"
    QA_GRAPH = "qa_graph"


class RoutePolicy(BaseModel):
    allow_web: bool = False
    notebook_only: bool = False
    has_user_context: bool = False
    has_course_context: bool = False
    has_notebook_context: bool = False
    has_trace: bool = False
    has_web_search_tool: bool = False
    source_policy: str = SourcePolicy.OPEN_TOOLS.value


class RouteDecision(BaseModel):
    route: BoundaryRoute
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    target_graph_type: GraphType
    bypass_qagraph: bool = False
    uses_trace: bool = False
    boundary: dict[str, Any] = Field(default_factory=dict)
    policy: RoutePolicy


def decide_route(
    state: OrchestratorState,
    *,
    quiz_resolution: QuizRequestResolution | None = None,
) -> RouteDecision:
    message = _message(state)
    policy = build_route_policy(state)
    time_context = runtime_time_context(state)
    boundary = classify_question_boundary(
        message,
        current_date=time_context.get("currentDate"),
    ).as_dict()
    lightweight_intent = classify_lightweight_answer_intent(message)
    quiz_resolution = quiz_resolution or resolve_quiz_request(message, _quiz_context(state))

    if boundary.get("category") == QUESTION_META_TOOL_USAGE:
        return RouteDecision(
            route=BoundaryRoute.META_TOOL_USAGE,
            confidence=0.95,
            reason="用户询问上一轮工具/联网调用记录。",
            target_graph_type=GraphType.ORCHESTRATOR,
            bypass_qagraph=True,
            uses_trace=True,
            boundary=boundary,
            policy=policy,
        )

    if lightweight_intent == "simple_fact":
        return RouteDecision(
            route=BoundaryRoute.SIMPLE_FACT,
            confidence=0.96,
            reason="命中确定性简单事实/计算题，直接回答。",
            target_graph_type=GraphType.ORCHESTRATOR,
            bypass_qagraph=True,
            boundary=boundary,
            policy=policy,
        )

    if lightweight_intent == "practice_generation" or quiz_resolution.is_quiz_request:
        target = GraphType.QUESTION_GENERATION
        bypass = True
        reason = quiz_resolution.reason or "命中练习/出题请求。"
        if _practice_depends_on_context(message) and not (policy.has_notebook_context or policy.has_course_context):
            target = GraphType.ORCHESTRATOR
            reason = "出题请求依赖 notebook/course 上下文，但当前上下文不足，需要澄清。"
        return RouteDecision(
            route=BoundaryRoute.PRACTICE_GENERATION,
            confidence=0.9,
            reason=reason,
            target_graph_type=target,
            bypass_qagraph=bypass,
            boundary=boundary,
            policy=policy,
        )

    if boundary.get("category") == QUESTION_REALTIME_OR_FRESH:
        return RouteDecision(
            route=BoundaryRoute.REALTIME_OR_FRESH,
            confidence=0.92,
            reason="命中实时/新鲜度问题。",
            target_graph_type=GraphType.QA if policy.allow_web else GraphType.ORCHESTRATOR,
            bypass_qagraph=not policy.allow_web,
            boundary=boundary,
            policy=policy,
        )

    return RouteDecision(
        route=BoundaryRoute.QA_GRAPH,
        confidence=0.8,
        reason="解释、教学、notebook QA 或普通问答进入 QAGraph。",
        target_graph_type=GraphType.QA,
        bypass_qagraph=False,
        boundary=boundary,
        policy=policy,
    )


def build_route_policy(state: OrchestratorState) -> RoutePolicy:
    source_policy = _source_policy(state)
    notebook_only = source_policy == SourcePolicy.NOTEBOOK_ONLY.value
    has_web_search_tool = _has_web_search_tool(state)
    return RoutePolicy(
        allow_web=(
            not notebook_only
            and has_web_search_tool
            and source_policy in {SourcePolicy.OPEN_TOOLS.value, SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value}
        ),
        notebook_only=notebook_only,
        has_user_context=bool(str(state.get("user_id") or "").strip()),
        has_course_context=bool(str(state.get("course_id") or "").strip()),
        has_notebook_context=bool(str(state.get("notebook_id") or "").strip()),
        has_trace=extract_previous_tool_trace(list(state.get("messages") or [])) is not None,
        has_web_search_tool=has_web_search_tool,
        source_policy=source_policy,
    )


def build_current_tool_trace(state: OrchestratorState, policy: RoutePolicy | None = None) -> dict[str, Any]:
    policy = policy or build_route_policy(state)
    time_context = runtime_time_context(state)
    return {
        "currentDate": time_context.get("currentDate"),
        "timezone": time_context.get("timezone"),
        "knowledgeCutoff": time_context.get("knowledgeCutoff"),
        "hasWebSearchTool": policy.has_web_search_tool,
        "webSearchEnabled": policy.allow_web,
        "toolCallCount": 0,
        "toolCalls": [],
        "didUseWebSearch": False,
        "didUseAnyTool": False,
    }


def extract_previous_tool_trace(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        trace = message.get("toolInvocationTrace")
        if isinstance(trace, dict):
            return normalize_tool_trace(trace)
        process = message.get("process")
        if not isinstance(process, dict):
            continue
        raw_calls = process.get("toolCalls")
        if not isinstance(raw_calls, list):
            continue
        calls = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("capability") or raw.get("name") or raw.get("tool") or "").strip()
            if not name:
                continue
            status = str(raw.get("status") or "").strip() or "unknown"
            calls.append({"name": name, "type": "web" if "search" in name.lower() else "tool", "status": status})
        if calls:
            did_use_web = any(call["type"] == "web" and call["status"] == ToolStatus.SUCCESS.value for call in calls)
            return normalize_tool_trace(
                {
                    "toolCallCount": len(calls),
                    "toolCalls": calls,
                    "didUseWebSearch": did_use_web,
                    "didUseAnyTool": True,
                }
            )
    return None


def normalize_tool_trace(raw: dict[str, Any]) -> dict[str, Any]:
    calls = raw.get("toolCalls") if isinstance(raw.get("toolCalls"), list) else []
    safe_calls = [dict(item) for item in calls if isinstance(item, dict)]
    tool_call_count = int(raw.get("toolCallCount") or len(safe_calls) or 0)
    return {
        "currentDate": raw.get("currentDate"),
        "timezone": raw.get("timezone"),
        "knowledgeCutoff": raw.get("knowledgeCutoff"),
        "hasWebSearchTool": bool(raw.get("hasWebSearchTool")),
        "webSearchEnabled": bool(raw.get("webSearchEnabled")),
        "toolCallCount": tool_call_count,
        "toolCalls": safe_calls,
        "didUseWebSearch": bool(raw.get("didUseWebSearch")),
        "didUseAnyTool": bool(raw.get("didUseAnyTool") or tool_call_count > 0),
    }


def runtime_time_context(state: OrchestratorState) -> dict[str, Any]:
    raw = state.get("runtime_time_context")
    if isinstance(raw, dict):
        timezone = str(raw.get("timezone") or _default_timezone()).strip() or _default_timezone()
        return {
            "currentDate": raw.get("currentDate"),
            "timezone": timezone,
            "knowledgeCutoff": raw.get("knowledgeCutoff") or os.getenv("KNOWLEDGE_CUTOFF") or None,
        }
    timezone = _default_timezone()
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        timezone = "UTC"
        now = datetime.now(ZoneInfo("UTC"))
    return {
        "currentDate": now.date().isoformat(),
        "timezone": timezone,
        "knowledgeCutoff": os.getenv("KNOWLEDGE_CUTOFF") or None,
    }


def _message(state: OrchestratorState) -> str:
    return " ".join(str(state.get("user_message") or "").split()).strip()


def _source_policy(state: OrchestratorState) -> str:
    candidate = str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value)
    try:
        return SourcePolicy(candidate).value
    except ValueError:
        return SourcePolicy.OPEN_TOOLS.value


def _has_web_search_tool(state: OrchestratorState) -> bool:
    runtime_context = state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {}
    capabilities = runtime_context.get("available_capabilities")
    if capabilities is None:
        return False
    return ToolCapability.WEB_SEARCH.value in {str(item) for item in list(capabilities or [])}


def _practice_depends_on_context(message: str) -> bool:
    return any(token in message for token in ("我的笔记", "我的资料", "notebook", "课程", "这门课", "当前资料", "这份资料"))


def _default_timezone() -> str:
    return str(os.getenv("APP_TIMEZONE") or os.getenv("TZ") or "Asia/Shanghai").strip() or "Asia/Shanghai"


def _quiz_context(state: OrchestratorState) -> dict[str, Any]:
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    memory = runtime_context.get("memory") if isinstance(runtime_context.get("memory"), dict) else {}
    session_memory = (
        runtime_context.get("session_memory")
        if isinstance(runtime_context.get("session_memory"), dict)
        else {}
    )
    context: dict[str, Any] = {
        "user_id": state.get("user_id", ""),
        "notebook_id": state.get("notebook_id"),
        "course_id": state.get("course_id"),
        "thread_id": state.get("thread_id"),
        "subject_id": runtime_context.get("selected_subject_id") or runtime_context.get("subject_id") or state.get("notebook_id"),
        "subject_name": runtime_context.get("subject_name"),
        "current_question": runtime_context.get("current_question"),
        "current_practice_question": runtime_context.get("current_practice_question"),
        "last_practice_pack": runtime_context.get("last_practice_pack"),
        "current_question_topic": runtime_context.get("current_question_topic"),
        "topic": runtime_context.get("topic"),
        "active_topic": runtime_context.get("active_topic"),
        "last_topic": runtime_context.get("last_topic"),
        "weak_points": runtime_context.get("weak_points"),
        "recent_topics": runtime_context.get("recent_topics"),
        "learner_stage": runtime_context.get("learner_stage"),
        "training_mode": runtime_context.get("training_mode"),
    }
    if session_memory.get("active_topic"):
        context["last_topic"] = session_memory.get("active_topic")
        context["active_topic"] = session_memory.get("active_topic")
    if session_memory.get("current_question"):
        context["current_question"] = session_memory.get("current_question")
    if session_memory.get("current_question_topic"):
        context["current_question_topic"] = session_memory.get("current_question_topic")
    if memory.get("recent_topics"):
        context["recent_topics"] = memory.get("recent_topics")
    if memory.get("weak_points"):
        context["weak_points"] = memory.get("weak_points")
    return {key: value for key, value in context.items() if value not in (None, "", [], {})}
