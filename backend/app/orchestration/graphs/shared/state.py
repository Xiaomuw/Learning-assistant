from __future__ import annotations

from typing import Any, Literal, TypedDict


class BaseLearningState(TypedDict, total=False):
    """Serializable baseline state shared by next-generation graphs.

    Runtime dependencies such as DB sessions, model clients and tool instances
    must be passed through graph factories or service layers, never through
    this state.
    """

    run_id: str
    tenant_id: str | None
    user_id: str
    message_id: str | None
    request_id: str | None
    client_request_id: str | None
    notebook_id: str | None
    course_id: str | None
    thread_id: str | None
    graph_type: Literal["orchestrator", "qa", "question_generation", "mastery"]
    graph_version: str
    source_policy: Literal["notebook_only", "notebook_plus_external", "open_tools"]
    allow_web: bool
    web_search_requested: bool
    user_message: str | None
    messages: list[dict[str, Any]]
    concepts: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    trace_records: list[dict[str, Any]]
    learning_events: list[dict[str, Any]]
    final_response: dict[str, Any]
    errors: list[dict[str, Any]]
