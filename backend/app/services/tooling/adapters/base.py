from __future__ import annotations

from typing import Protocol

from app.services.tooling.schemas import ToolExecutionRequest, ToolRegistration
from app.shared.schemas.agent_graphs import ToolResult


class ToolAdapter(Protocol):
    registration: ToolRegistration

    def invoke(self, request: ToolExecutionRequest) -> ToolResult:
        """Execute provider-specific logic and return a normalized result."""

