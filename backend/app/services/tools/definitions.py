from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.shared.schemas.qa_runtime import AgentRequest


@dataclass
class ToolDefinition:
    name: str
    description: str
    args_schema: type[BaseModel]
    scope: str
    executor: Callable[[AgentRequest, dict[str, Any]], dict[str, Any]]
    is_external: bool = False
    availability: Callable[[AgentRequest], bool] | None = None

    def to_langchain_tool(self, agent_request: AgentRequest) -> StructuredTool:
        def _runner(**kwargs: Any) -> str:
            payload = self.executor(agent_request, kwargs)
            return json.dumps(payload, ensure_ascii=False)

        return StructuredTool.from_function(
            func=_runner,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )
