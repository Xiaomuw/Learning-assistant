"""Shared Q&A runtime contracts used across domains and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnswerSchema(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    thinking: str = Field(min_length=1, max_length=1200)
    steps: list[str] = Field(default_factory=list, min_length=1, max_length=6)
    mistakes: str = Field(default="", max_length=500)
    similar: list[str] = Field(default_factory=list, min_length=2, max_length=3)
    final_answer: str = Field(default="", max_length=1200)


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
