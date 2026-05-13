from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.infrastructure.llm.langsmith import trace_run
from app.services.tools.args import (
    LearningProfileArgs,
    MCPWebReadArgs,
    NotebookSearchArgs,
    RecommendQuestionsArgs,
    SessionSummaryArgs,
    TavilySearchArgs,
)
from app.services.tools.internal_tools import (
    get_session_summary,
    get_user_learning_profile,
    recommend_questions,
    search_notebook_context,
)
from app.services.tools.mcp_tools import (
    mcp_read_available,
    mcp_search_available,
    mcp_web_read,
    mcp_web_search,
)
from app.services.tools.tavily_tool import tavily_available, tavily_web_search
from app.shared.schemas.qa_runtime import AgentRequest, ToolCall, ToolResult

NOTEBOOK_RETRIEVE = "notebook_retrieve"
WEB_SEARCH = "web_search"
WEB_EXTRACT = "web_extract"
SESSION_SUMMARY = "session_summary"
LEARNING_PROFILE = "learning_profile"
QUESTION_RECOMMEND = "question_recommend"


@dataclass
class CapabilityToolDefinition:
    name: str
    capability: str
    description: str
    args_schema: type[BaseModel]
    scope: str
    executor: Callable[[AgentRequest, dict[str, Any]], dict[str, Any]]
    provider: str = "internal"
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


class CapabilityToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityToolDefinition] = {}

    def register(self, definition: CapabilityToolDefinition) -> None:
        self._definitions[definition.name] = definition

    def get_definition(self, name: str) -> CapabilityToolDefinition | None:
        return self._definitions.get(name)

    def get_available_tools(
        self,
        *,
        scope: str = "qa",
        agent_request: AgentRequest | None = None,
    ) -> list[Any]:
        definitions: list[CapabilityToolDefinition] = []
        runtime_context = agent_request.runtime_context if agent_request is not None else {}
        guard = (
            dict(runtime_context.get("guard") or {})
            if isinstance(runtime_context.get("guard"), dict)
            else {}
        )
        has_tool_policy = bool(guard) or "allow_tools" in runtime_context
        has_search_policy = bool(guard) or "allow_search" in runtime_context
        allow_tools = (
            bool(runtime_context.get("allow_tools", False) or guard.get("allow_tools", False))
            if has_tool_policy
            else False
        )
        allow_search = (
            bool(runtime_context.get("allow_search", False) or guard.get("allow_search", False))
            if has_search_policy
            else False
        )
        notebook_policy = str(runtime_context.get("notebook_policy") or guard.get("notebook_policy") or "").strip()
        search_policy = str(runtime_context.get("search_policy") or guard.get("search_policy") or "").strip()

        for definition in self._definitions.values():
            if definition.scope != scope:
                continue
            if agent_request is not None and not allow_tools:
                continue
            if agent_request is not None and definition.capability == NOTEBOOK_RETRIEVE and notebook_policy == "skip":
                continue
            if (
                agent_request is not None
                and definition.capability in {WEB_SEARCH, WEB_EXTRACT}
                and (not allow_search or search_policy == "forbidden")
            ):
                continue
            if agent_request is not None and definition.availability is not None:
                try:
                    if not definition.availability(agent_request):
                        continue
                except Exception:
                    continue
            definitions.append(definition)
        if agent_request is None:
            return definitions
        return [definition.to_langchain_tool(agent_request) for definition in definitions]


class CapabilityToolExecutor:
    def __init__(self, registry: CapabilityToolRegistry) -> None:
        self._registry = registry

    def execute(
        self,
        tool_call: ToolCall,
        *,
        agent_request: AgentRequest,
        scope: str = "qa",
    ) -> ToolResult:
        definition = self._registry.get_definition(tool_call.name)
        if definition is None or definition.scope != scope:
            return ToolResult(
                name=tool_call.name,
                success=False,
                payload={},
                call_id=tool_call.call_id,
                error="工具能力未注册",
            )

        with trace_run(
            name=f"qa_agent.tool.{definition.capability}",
            run_type="tool",
            inputs={
                "tool_name": definition.name,
                "capability": definition.capability,
                "provider": definition.provider,
                "scope": scope,
                "has_args": bool(tool_call.args),
                "user_id": agent_request.user_id,
                "session_id": agent_request.session_id,
                "subject_id": agent_request.subject_id,
            },
            metadata={
                "tool_name": definition.name,
                "capability": definition.capability,
                "provider": definition.provider,
                "scope": scope,
                "subject_id": agent_request.subject_id,
                "is_external": bool(definition.is_external),
            },
            tags=[
                "qa-runtime",
                "tool-call",
                f"capability:{definition.capability}",
                "external-tool" if definition.is_external else "internal-tool",
            ],
        ) as tool_run:
            try:
                payload = definition.executor(agent_request, tool_call.args)
                provider = str(payload.get("_tool_provider") or definition.provider)
                payload["_tool_capability"] = definition.capability
                payload["_tool_provider"] = provider
                doc_count = int(payload.get("doc_count") or len(payload.get("documents") or []))
                result = ToolResult(
                    name=definition.name,
                    success=True,
                    payload=payload,
                    call_id=tool_call.call_id,
                )
                tool_run.metadata.update({"success": True, "provider": provider})
                tool_run.end(
                    outputs={
                        "success": True,
                        "capability": definition.capability,
                        "provider": provider,
                        "doc_count": doc_count,
                        "payload_keys": sorted(str(key) for key in payload.keys() if not str(key).startswith("_")),
                    }
                )
                return result
            except Exception as exc:
                error_message = str(exc)
                tool_run.metadata.update(
                    {
                        "success": False,
                        "error_type": type(exc).__name__,
                    }
                )
                tool_run.end(
                    outputs={
                        "success": False,
                        "capability": definition.capability,
                        "provider": definition.provider,
                        "error_type": type(exc).__name__,
                    }
                )
                return ToolResult(
                    name=definition.name,
                    success=False,
                    payload={
                        "_tool_capability": definition.capability,
                        "_tool_provider": definition.provider,
                    },
                    call_id=tool_call.call_id,
                    error=error_message,
                )


def _web_search_available(agent_request: AgentRequest) -> bool:
    return mcp_search_available(agent_request) or tavily_available(agent_request)


def _execute_web_search(agent_request: AgentRequest, args: dict[str, Any]) -> dict[str, Any]:
    if mcp_search_available(agent_request):
        payload = mcp_web_search(agent_request, args)
        payload["_tool_provider"] = "mcp"
        _mark_web_documents(payload, provider="mcp")
        return payload
    if tavily_available(agent_request):
        payload = tavily_web_search(agent_request, args)
        payload["_tool_provider"] = "tavily"
        _mark_web_documents(payload, provider="tavily")
        return payload
    raise RuntimeError("web_search provider unavailable")


def _execute_web_extract(agent_request: AgentRequest, args: dict[str, Any]) -> dict[str, Any]:
    payload = mcp_web_read(agent_request, args)
    payload["_tool_provider"] = "mcp"
    _mark_web_documents(payload, provider="mcp")
    return payload


def _execute_notebook_retrieve(agent_request: AgentRequest, args: dict[str, Any]) -> dict[str, Any]:
    payload = search_notebook_context(agent_request, args)
    payload["_tool_provider"] = "notebook"
    return payload


def _mark_web_documents(payload: dict[str, Any], *, provider: str) -> None:
    for document in list(payload.get("documents") or []):
        if not isinstance(document, dict):
            continue
        metadata = document.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            document["metadata"] = metadata
        metadata["retrieval_source"] = "web"
        metadata["provider"] = provider


def build_capability_tool_registry() -> CapabilityToolRegistry:
    registry = CapabilityToolRegistry()
    registry.register(
        CapabilityToolDefinition(
            name=NOTEBOOK_RETRIEVE,
            capability=NOTEBOOK_RETRIEVE,
            description=(
                "检索用户 notebook / 课程资料，作为可选学习参考。"
                "只有用户要求参考资料、需要核对课程内容，或需要私有资料补充时调用。"
            ),
            args_schema=NotebookSearchArgs,
            scope="qa",
            provider="notebook",
            executor=_execute_notebook_retrieve,
        )
    )
    registry.register(
        CapabilityToolDefinition(
            name=SESSION_SUMMARY,
            capability=SESSION_SUMMARY,
            description="读取当前会话摘要，了解最近讲到哪、当前目标和未解决点。",
            args_schema=SessionSummaryArgs,
            scope="qa",
            provider="internal",
            executor=get_session_summary,
        )
    )
    registry.register(
        CapabilityToolDefinition(
            name=LEARNING_PROFILE,
            capability=LEARNING_PROFILE,
            description="读取用户长期学习画像，包括薄弱点、最近主题和错误统计。",
            args_schema=LearningProfileArgs,
            scope="qa",
            provider="internal",
            executor=get_user_learning_profile,
        )
    )
    registry.register(
        CapabilityToolDefinition(
            name=QUESTION_RECOMMEND,
            capability=QUESTION_RECOMMEND,
            description="根据当前用户与 notebook 推荐适合继续练习的题目。",
            args_schema=RecommendQuestionsArgs,
            scope="qa",
            provider="internal",
            executor=recommend_questions,
        )
    )
    registry.register(
        CapabilityToolDefinition(
            name=WEB_SEARCH,
            capability=WEB_SEARCH,
            description=(
                "按需搜索外部网络，获取最新、官网、文档、来源或权威事实。"
                "普通稳定概念不要默认搜索。"
            ),
            args_schema=TavilySearchArgs,
            scope="qa",
            provider="web",
            executor=_execute_web_search,
            is_external=True,
            availability=_web_search_available,
        )
    )
    registry.register(
        CapabilityToolDefinition(
            name=WEB_EXTRACT,
            capability=WEB_EXTRACT,
            description="读取用户明确提供或本轮搜索返回的网页内容，并提取正文摘要。",
            args_schema=MCPWebReadArgs,
            scope="qa",
            provider="mcp",
            executor=_execute_web_extract,
            is_external=True,
            availability=mcp_read_available,
        )
    )
    return registry


tool_registry = build_capability_tool_registry()
tool_executor = CapabilityToolExecutor(tool_registry)
