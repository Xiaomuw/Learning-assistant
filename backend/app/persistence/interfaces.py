from __future__ import annotations

from typing import Any, Protocol

from app.shared.schemas.agent_graphs import LearningEvent, ToolResult


class GraphRunRepository(Protocol):
    def start_run(self, payload: dict[str, Any]) -> str:
        """Create a graph run audit row and return graph_run_id."""

    def finish_run(self, graph_run_id: str, payload: dict[str, Any]) -> None:
        """Finalize a graph run audit row."""

    def record_audit_event(self, payload: dict[str, Any]) -> None:
        """Record lightweight orchestrator audit data."""


class LearningEventRepository(Protocol):
    def append(self, event: LearningEvent) -> str:
        """Persist a learning event and return its id."""

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        """Read recent learning events for a user."""


class ToolRunRepository(Protocol):
    def record_tool_run(self, result: ToolResult, *, graph_run_id: str) -> str:
        """Persist normalized tool execution audit."""


class QuestionItemRepository(Protocol):
    def create_question_item(self, payload: dict[str, Any]) -> str:
        """Persist a generated or imported question item."""

    def find_similar(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        """Find potentially duplicate question items."""


class AttemptRepository(Protocol):
    def create_attempt(self, payload: dict[str, Any]) -> str:
        """Persist a user answer attempt."""

    def list_recent_attempts(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read recent attempts for mastery evaluation."""


class MasterySnapshotRepository(Protocol):
    def upsert_snapshot(self, payload: dict[str, Any]) -> str:
        """Create or update a mastery snapshot."""

    def list_snapshots(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read mastery snapshots for a user."""


class NotebookChunkRepository(Protocol):
    def search_chunks(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        """Search notebook chunks through the persistence boundary."""


class ConceptRepository(Protocol):
    def resolve_concept(self, name: str) -> dict[str, Any] | None:
        """Resolve or read a concept by name."""

    def upsert_concept(self, payload: dict[str, Any]) -> str:
        """Persist a concept definition."""

