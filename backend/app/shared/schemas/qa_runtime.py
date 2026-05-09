"""Shared Q&A runtime contracts used across domains and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.shared.markdown_cleaning import strip_markdown_artifacts, strip_markdown_list


class AnswerSchema(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    thinking: str = Field(min_length=1, max_length=1200)
    steps: list[str] = Field(default_factory=list, min_length=1, max_length=6)
    mistakes: str = Field(default="", max_length=500)
    similar: list[str] = Field(default_factory=list, min_length=2, max_length=3)
    final_answer: str = Field(default="", max_length=1200)

    @field_validator("topic", "thinking", "mistakes", "final_answer", mode="before")
    @classmethod
    def _coerce_text_field(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return strip_markdown_artifacts(value)
        if isinstance(value, list):
            return "；".join(strip_markdown_list([str(item) for item in value]))
        if isinstance(value, dict):
            return strip_markdown_artifacts("；".join(f"{key}: {item}" for key, item in value.items()))
        return strip_markdown_artifacts(str(value))

    @field_validator("steps", mode="before")
    @classmethod
    def _coerce_steps(cls, value: Any) -> list[str]:
        return _coerce_string_list(value, fallback=["继续围绕这个问题拆解核心概念"])

    @field_validator("similar", mode="before")
    @classmethod
    def _coerce_similar(cls, value: Any) -> list[str]:
        items = _coerce_string_list(
            value,
            fallback=["继续追问这个主题", "结合你的笔记继续解释"],
        )
        while len(items) < 2:
            items.append("结合你的笔记继续解释")
        return items[:3]


def _coerce_string_list(value: Any, *, fallback: list[str]) -> list[str]:
    if value is None:
        return list(fallback)
    if isinstance(value, list):
        items = strip_markdown_list([str(item) for item in value])
        return items or list(fallback)
    if isinstance(value, str):
        stripped = strip_markdown_artifacts(value)
        if not stripped:
            return list(fallback)
        separators = ("\n", "；", ";")
        parts = [stripped]
        for separator in separators:
            if separator in stripped:
                parts = [part.strip(" -\t") for part in stripped.split(separator)]
                break
        items = [part for part in parts if part]
        return items or [stripped]
    cleaned = strip_markdown_artifacts(str(value))
    return [cleaned] if cleaned else list(fallback)


@dataclass
class AgentRequest:
    user_id: str
    session_id: str
    subject_id: str
    subject_name: str
    subject_description: str
    question: str
    question_type: str
    memory: dict[str, Any] = field(default_factory=dict)
    user_style_name: str = ""
    user_style_prompt: str = ""
    short_term_messages: list[dict[str, Any]] = field(default_factory=list)
    short_term_context: str = ""
    session_memory: dict[str, Any] = field(default_factory=dict)
    session_memory_context: str = ""
    long_term_context: str = ""
    input_modalities: tuple[str, ...] = ("text",)
    model_name: str = ""
    runtime_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str = ""


@dataclass
class ToolResult:
    name: str
    success: bool
    payload: dict[str, Any]
    call_id: str = ""
    error: str = ""


@dataclass
class AgentExecutionResult:
    execution_mode: Literal[
        "direct_answer",
        "tool_calling",
        "structured_output",
        "deterministic_context",
    ] = "structured_output"
    raw_output: Any = None
    answer: AnswerSchema | None = None
    retrieved_docs: list[dict[str, Any]] = field(default_factory=list)
    is_rewritten: bool = False
    contextual_query: str = ""
    retrieval_diagnosis: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_decision_rounds: list[dict[str, Any]] = field(default_factory=list)
    reasoning_summary: str = ""
    source_usage: Literal["none", "model", "notebook", "web", "mixed"] = "model"
    degraded: bool = False
    selected_model_profile: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    model_unavailable_reason: str = ""
    learner_context_summary: str = ""
    primary_model_id: str = ""
    fallback_model_id: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    model_attempts: list[dict[str, Any]] = field(default_factory=list)
    streaming_mode: str = "node"
    streaming_token_count: int = 0
    streaming_degraded_reason: str = ""
