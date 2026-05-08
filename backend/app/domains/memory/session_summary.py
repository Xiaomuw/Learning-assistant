"""
Session Summary Memory
======================
负责中期会话摘要的规则生成、LLM 增强与格式化。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_chat_llm, get_model_access_key
from app.infrastructure.llm.structured import invoke_with_schema
from app.domains.memory.short_term import build_short_term_context, is_context_dependent_question

EMPTY_SESSION_MEMORY = {
    "summary_text": "",
    "active_topic": "",
    "current_goal": "",
    "open_loops": [],
    "resolved_points": [],
    "last_question_type": "",
    "last_updated_at": "",
    "pending_check": {},
    "teaching_phase": "",
    "stuck_count": 0,
    "last_teaching_action": "",
    "used_analogies": [],
}

MAX_OPEN_LOOPS = 5
MAX_RESOLVED_POINTS = 5


class SessionMemoryEnhancement(BaseModel):
    summary_text: str = Field(description="当前会话的自然语言摘要")
    current_goal: str = Field(description="当前会话最主要的学习目标")
    open_loops: list[str] = Field(default_factory=list, description="还没有完全解决的问题")
    resolved_points: list[str] = Field(default_factory=list, description="当前会话已经讲清楚的关键点")


SESSION_MEMORY_SYSTEM_PROMPT = """\
你是学习会话摘要器。你的任务是根据当前会话已有摘要、最近对话、当前问题和本轮结果，
更新一份中期会话记忆，帮助后续追问保持上下文连续性。

## 当前已有会话摘要
{previous_session_memory_context}

## 最近对话上下文（短期记忆）
{short_term_context}

## 用户长期学习记忆
{long_term_context}

## 当前笔记本
{subject_name}

## 当前问题
{question}

## 当前问题类型
{question_type}

## 本轮讲解结果
{explanation_json}

## 本轮题包
{quiz_json}

## 本轮最终回答
{final_answer}

请只输出结构化结果，用于更新：
- summary_text：一句到两句概括当前会话已经讲到哪
- current_goal：当前阶段用户最可能想完成什么
- open_loops：还没完全解决、适合下一轮继续追问的点
- resolved_points：本轮明确讲清楚或已完成的关键点
"""

SESSION_MEMORY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SESSION_MEMORY_SYSTEM_PROMPT),
        ("human", "请更新这份会话摘要。"),
    ]
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_session_memory(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return dict(EMPTY_SESSION_MEMORY)

    normalized = dict(EMPTY_SESSION_MEMORY)
    normalized["summary_text"] = str(raw.get("summary_text", "") or "")
    normalized["active_topic"] = str(raw.get("active_topic", "") or "")
    normalized["current_goal"] = str(raw.get("current_goal", "") or "")
    normalized["open_loops"] = [
        str(item) for item in list(raw.get("open_loops", []) or []) if str(item).strip()
    ]
    normalized["resolved_points"] = [
        str(item)
        for item in list(raw.get("resolved_points", []) or [])
        if str(item).strip()
    ]
    normalized["last_question_type"] = str(raw.get("last_question_type", "") or "")
    normalized["last_updated_at"] = str(raw.get("last_updated_at", "") or "")
    pending_check = raw.get("pending_check")
    normalized["pending_check"] = pending_check if isinstance(pending_check, dict) else {}
    normalized["teaching_phase"] = str(raw.get("teaching_phase", "") or "")
    try:
        normalized["stuck_count"] = int(raw.get("stuck_count", 0) or 0)
    except (TypeError, ValueError):
        normalized["stuck_count"] = 0
    normalized["last_teaching_action"] = str(raw.get("last_teaching_action", "") or "")
    normalized["used_analogies"] = [
        item
        for item in list(raw.get("used_analogies", []) or [])
        if isinstance(item, dict) and item.get("knowledge_point") and item.get("analogy")
    ][:10]
    return normalized


def build_session_memory_context(session_memory: dict[str, Any] | None) -> str:
    memory = normalize_session_memory(session_memory)
    lines: list[str] = []

    if memory["summary_text"]:
        lines.append(f"会话摘要：{memory['summary_text']}")
    if memory["active_topic"]:
        lines.append(f"当前主主题：{memory['active_topic']}")
    if memory["current_goal"]:
        lines.append(f"当前学习目标：{memory['current_goal']}")
    if memory["open_loops"]:
        lines.append(f"未解决点：{', '.join(memory['open_loops'][:MAX_OPEN_LOOPS])}")
    if memory["resolved_points"]:
        lines.append(f"已解决要点：{', '.join(memory['resolved_points'][:MAX_RESOLVED_POINTS])}")
    if memory.get("pending_check"):
        pending = memory["pending_check"]
        lines.append(
            f"待回答检查点：{pending.get('knowledge_point', '当前知识点')} - "
            f"{pending.get('prompt', '')}"
        )

    if not lines:
        return "（当前会话暂无中期摘要）"
    return "\n".join(lines)


def _pick_active_topic(
    question: str,
    question_type: str,
    explanation: dict[str, Any],
    quiz_items: list[dict[str, Any]],
    quiz_request: dict[str, Any] | None,
    previous_session_memory: dict[str, Any],
) -> str:
    previous_topic = str(previous_session_memory.get("active_topic", "") or "").strip()
    if question_type in {"meta", "smalltalk"} and previous_topic:
        return previous_topic

    final_text = " ".join(
        [
            str(explanation.get("thinking", "") or ""),
            " ".join(str(item) for item in list(explanation.get("steps", []) or [])),
        ]
    )
    is_failed_practice_generation = (
        question_type == "practice"
        and not quiz_items
        and any(marker in final_text for marker in ("质量门", "没有保存题目", "未通过"))
    )
    requested_topic = ""
    if isinstance(quiz_request, dict):
        requested_topic = str(
            quiz_request.get("requested_topic") or quiz_request.get("active_topic") or quiz_request.get("topic") or ""
        ).strip()
    if requested_topic:
        return requested_topic
    if is_failed_practice_generation and previous_topic:
        return previous_topic

    topic = str(explanation.get("topic", "") or "").strip()
    if topic:
        return topic

    for quiz_item in quiz_items:
        knowledge_point = str(quiz_item.get("knowledge_point", "") or "").strip()
        if knowledge_point:
            return knowledge_point

    if previous_topic and question_type in {"concept", "problem", "review", "practice"}:
        return previous_topic

    return question[:40].strip()


def _pick_current_goal(
    question_type: str,
    question: str,
    active_topic: str,
    previous_session_memory: dict[str, Any],
    *,
    failed_practice_generation: bool = False,
) -> str:
    anchor = active_topic or question[:40].strip() or "当前主题"
    previous_goal = str(previous_session_memory.get("current_goal", "") or "").strip()

    if question_type == "concept":
        return f"理解「{anchor}」的概念、原理与适用场景"
    if question_type == "problem":
        return f"掌握「{anchor}」相关题目的思路与做法"
    if question_type == "review":
        return f"复习并巩固「{anchor}」的关键知识点"
    if question_type == "practice":
        if failed_practice_generation:
            return f"围绕「{anchor}」重新生成可用练习题"
        return f"围绕「{anchor}」练习并检查掌握情况"
    if question_type in {"meta", "smalltalk"}:
        return previous_goal
    return f"围绕「{anchor}」继续学习"


def _unique_recent(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered[:limit]


def _extract_rule_resolved_points(
    explanation: dict[str, Any],
    quiz_items: list[dict[str, Any]],
    final_answer: str,
) -> list[str]:
    points: list[str] = []

    thinking = str(explanation.get("thinking", "") or "").strip()
    if thinking:
        points.append(thinking)

    for step in list(explanation.get("steps", []) or [])[:2]:
        step_text = str(step).strip()
        if step_text:
            points.append(step_text)

    if quiz_items:
        topic = str(quiz_items[0].get("knowledge_point", "") or "").strip()
        points.append(f"已生成 {len(quiz_items)} 道围绕「{topic or '当前主题'}」的练习题")

    if final_answer and not points:
        points.append(str(final_answer).strip())

    return _unique_recent(points, MAX_RESOLVED_POINTS)


def _build_rule_open_loops(
    previous_session_memory: dict[str, Any],
    question_type: str,
    active_topic: str,
    quiz_items: list[dict[str, Any]],
    *,
    failed_practice_generation: bool = False,
) -> list[str]:
    previous_open_loops = [
        str(item).strip()
        for item in list(previous_session_memory.get("open_loops", []) or [])
        if str(item).strip()
    ]

    if question_type == "practice":
        if failed_practice_generation:
            failure_loop = f"重新尝试围绕「{active_topic or '当前主题'}」生成有效练习题"
            return _unique_recent([failure_loop, *previous_open_loops], MAX_OPEN_LOOPS)
        practice_loop = f"继续完成围绕「{active_topic or '当前主题'}」的练习，并核对答案"
        return _unique_recent([practice_loop, *previous_open_loops], MAX_OPEN_LOOPS)

    if question_type in {"smalltalk", "meta"}:
        return _unique_recent(previous_open_loops, MAX_OPEN_LOOPS)

    return _unique_recent(previous_open_loops, MAX_OPEN_LOOPS)


def _build_rule_summary(
    question: str,
    question_type: str,
    active_topic: str,
    current_goal: str,
    resolved_points: list[str],
    open_loops: list[str],
) -> str:
    parts = [f"当前会话正在围绕「{active_topic or '当前主题'}」学习。"]

    if current_goal:
        parts.append(f"当前目标是：{current_goal}。")

    if resolved_points:
        parts.append(f"最近已经讲清楚：{resolved_points[0]}。")

    if open_loops:
        parts.append(f"接下来还可以继续：{open_loops[0]}。")
    elif question_type in {"concept", "problem", "review"}:
        parts.append("当前这一轮的核心问题已经得到解释。")
    elif question_type == "practice":
        parts.append("当前进入练习巩固阶段。")

    return "".join(parts)[:400]


def should_enhance_session_memory(
    question: str,
    question_type: str,
    short_term_messages: list[dict[str, Any]],
) -> bool:
    if question_type not in {"concept", "problem", "review", "practice"}:
        return False

    total_messages = len(short_term_messages) + 2
    return total_messages >= 4 or is_context_dependent_question(question)


def _get_session_memory_llm(model_name: str | None = None):
    model_override = os.getenv("SESSION_MEMORY_MODEL") or None
    return get_chat_llm(
        default_model=DEFAULT_CHAT_MODEL,
        temperature=0.1,
        model_override=model_override or model_name,
    )


def _invoke_session_memory_enhancement(
    payload: dict[str, Any],
    *,
    model_name: str | None = None,
) -> SessionMemoryEnhancement:
    return invoke_with_schema(
        SESSION_MEMORY_PROMPT,
        _get_session_memory_llm(model_name),
        SessionMemoryEnhancement,
        payload,
        model_name=model_name,
    )


def update_session_memory(
    *,
    previous_session_memory: dict[str, Any] | None,
    short_term_messages: list[dict[str, Any]],
    short_term_context: str,
    long_term_context: str,
    question: str,
    question_type: str,
    explanation: dict[str, Any],
    quiz_items: list[dict[str, Any]],
    final_answer: str,
    subject_name: str,
    quiz_request: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    previous = normalize_session_memory(previous_session_memory)
    failed_practice_generation = (
        question_type == "practice"
        and not quiz_items
        and any(marker in str(final_answer or "") for marker in ("质量门", "没有保存题目", "未通过"))
    )

    active_topic = _pick_active_topic(
        question=question,
        question_type=question_type,
        explanation=explanation,
        quiz_items=quiz_items,
        quiz_request=quiz_request,
        previous_session_memory=previous,
    )
    current_goal = _pick_current_goal(
        question_type,
        question,
        active_topic,
        previous,
        failed_practice_generation=failed_practice_generation,
    )
    resolved_points = _unique_recent(
        [
            *_extract_rule_resolved_points(explanation, quiz_items, final_answer),
            *previous.get("resolved_points", []),
        ],
        MAX_RESOLVED_POINTS,
    )
    open_loops = _build_rule_open_loops(
        previous_session_memory=previous,
        question_type=question_type,
        active_topic=active_topic,
        quiz_items=quiz_items,
        failed_practice_generation=failed_practice_generation,
    )

    summary_text = _build_rule_summary(
        question=question,
        question_type=question_type,
        active_topic=active_topic,
        current_goal=current_goal,
        resolved_points=resolved_points,
        open_loops=open_loops,
    )
    if question_type in {"meta", "smalltalk"} and previous.get("summary_text"):
        summary_text = str(previous["summary_text"])

    next_memory = {
        "summary_text": summary_text,
        "active_topic": active_topic,
        "current_goal": current_goal,
        "open_loops": open_loops,
        "resolved_points": resolved_points,
        "last_question_type": question_type,
        "last_updated_at": _utc_iso(),
        "pending_check": previous.get("pending_check", {}),
        "teaching_phase": previous.get("teaching_phase", ""),
        "stuck_count": previous.get("stuck_count", 0),
        "last_teaching_action": previous.get("last_teaching_action", ""),
        "used_analogies": previous.get("used_analogies", []),
    }

    if not should_enhance_session_memory(question, question_type, short_term_messages):
        return next_memory

    if not get_model_access_key():
        return next_memory

    try:
        result = _invoke_session_memory_enhancement(
            {
                "previous_session_memory_context": build_session_memory_context(previous),
                "short_term_context": short_term_context
                or build_short_term_context(short_term_messages),
                "long_term_context": long_term_context,
                "subject_name": subject_name,
                "question": question,
                "question_type": question_type,
                "explanation_json": json.dumps(explanation or {}, ensure_ascii=False),
                "quiz_json": json.dumps(quiz_items or [], ensure_ascii=False),
                "final_answer": final_answer or "",
            },
            model_name=model_name,
        )

        if result.summary_text.strip():
            next_memory["summary_text"] = result.summary_text.strip()[:400]
        if result.current_goal.strip():
            next_memory["current_goal"] = result.current_goal.strip()[:200]
        if result.open_loops:
            next_memory["open_loops"] = _unique_recent(
                [*result.open_loops, *open_loops],
                MAX_OPEN_LOOPS,
            )
        if result.resolved_points:
            next_memory["resolved_points"] = _unique_recent(
                [*result.resolved_points, *resolved_points],
                MAX_RESOLVED_POINTS,
            )

    except Exception as exc:
        logger.warning(f"⚠️ 会话摘要增强失败，保留规则摘要: {exc}")

    return next_memory
