from __future__ import annotations

from dataclasses import dataclass

from app.services.tooling.adapters.base import ToolAdapter
from app.services.tooling.adapters.mcp import MCPWebSearchAdapter
from app.services.tooling.adapters.notebook import NotebookRetrieveAdapter
from app.services.tooling.adapters.tavily import TavilyWebSearchAdapter
from app.shared.schemas.agent_graphs import ToolCapability


@dataclass(frozen=True)
class RegisteredTool:
    adapter: ToolAdapter

    @property
    def tool_id(self) -> str:
        return self.adapter.registration.tool_id

    @property
    def provider(self) -> str:
        return self.adapter.registration.provider

    @property
    def capability(self) -> ToolCapability:
        return self.adapter.registration.capability

    @property
    def enabled(self) -> bool:
        return self.adapter.registration.enabled


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, adapter: ToolAdapter) -> None:
        self._tools[adapter.registration.tool_id] = RegisteredTool(adapter=adapter)

    def get(self, tool_id: str) -> RegisteredTool | None:
        return self._tools.get(tool_id)

    def find_by_capability(
        self,
        capability: ToolCapability,
        *,
        provider: str | None = None,
        include_disabled: bool = False,
    ) -> list[RegisteredTool]:
        tools = [
            item
            for item in self._tools.values()
            if item.capability == capability
            and (provider is None or item.provider == provider)
            and (include_disabled or item.enabled)
        ]
        return sorted(tools, key=lambda item: item.tool_id)


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(NotebookRetrieveAdapter())
    registry.register(MCPWebSearchAdapter())
    registry.register(TavilyWebSearchAdapter())
    return registry
