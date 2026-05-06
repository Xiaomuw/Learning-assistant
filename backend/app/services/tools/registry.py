from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from app.infrastructure.llm.langsmith import trace_run
from app.services.tools.args import (
    LearningProfileArgs,
    MCPWebReadArgs,
    MCPWebSearchArgs,
    NotebookSearchArgs,
    RecommendQuestionsArgs,
    SessionSummaryArgs,
    TavilySearchArgs,
)
from app.services.tools.definitions import ToolDefinition
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


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._definitions[definition.name] = definition

    def register_external(
        self,
        *,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        scope: str = "qa",
        executor: Callable[[AgentRequest, dict[str, Any]], dict[str, Any]] | None = None,
        availability: Callable[[AgentRequest], bool] | None = None,
    ) -> None:
        self.register(
            ToolDefinition(
                name=name,
                description=description,
                args_schema=args_schema,
                scope=scope,
                executor=executor or (lambda _req, _args: {"message": "外部工具暂未接入"}),
                is_external=True,
                availability=availability,
            )
        )

    def get_definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def get_available_tools(
        self,
        *,
        scope: str = "qa",
        agent_request: AgentRequest | None = None,
    ) -> list[Any]:
        definitions: list[ToolDefinition] = []
        runtime_context = agent_request.runtime_context if agent_request is not None else {}
        guard = (
            dict(runtime_context.get("guard") or {})
            if isinstance(runtime_context.get("guard"), dict)
            else {}
        )
        has_guard_policy = bool(guard) or "allow_tools" in runtime_context or "allow_search" in runtime_context
        allow_tools = (
            bool(runtime_context.get("allow_tools", False) or guard.get("allow_tools", False))
            if has_guard_policy
            else True
        )
        allow_search = (
            bool(runtime_context.get("allow_search", False) or guard.get("allow_search", False))
            if has_guard_policy
            else True
        )
        notebook_policy = str(runtime_context.get("notebook_policy") or guard.get("notebook_policy") or "").strip()
        search_policy = str(runtime_context.get("search_policy") or guard.get("search_policy") or "").strip()
        for definition in self._definitions.values():
            if definition.scope != scope:
                continue
            if agent_request is not None and has_guard_policy and not allow_tools:
                continue
            if agent_request is not None and definition.name == "search_notebook_context" and notebook_policy == "skip":
                continue
            if (
                agent_request is not None
                and definition.is_external
                and "web" in definition.name
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


class ToolExecutor:
    def execute(
        self,
        tool_call: ToolCall,
        *,
        agent_request: AgentRequest,
        scope: str = "qa",
    ) -> ToolResult:
        definition = tool_registry.get_definition(tool_call.name)
        if definition is None or definition.scope != scope:
            return ToolResult(
                name=tool_call.name,
                success=False,
                payload={},
                call_id=tool_call.call_id,
                error="工具未注册",
            )

        with trace_run(
            name=f"qa_agent.tool.{tool_call.name or 'unknown'}",
            run_type="tool",
            inputs={
                "tool_name": tool_call.name,
                "scope": scope,
                "args": dict(tool_call.args),
                "user_id": agent_request.user_id,
                "session_id": agent_request.session_id,
                "subject_id": agent_request.subject_id,
            },
            metadata={
                "tool_name": tool_call.name,
                "scope": scope,
                "subject_id": agent_request.subject_id,
                "is_external": bool(definition.is_external),
            },
            tags=[
                "qa-runtime",
                "tool-call",
                f"tool:{tool_call.name or 'unknown'}",
                "external-tool" if definition.is_external else "internal-tool",
            ],
        ) as tool_run:
            try:
                payload = definition.executor(agent_request, tool_call.args)
                doc_count = int(payload.get("doc_count") or len(payload.get("documents") or []))
                result = ToolResult(
                    name=tool_call.name,
                    success=True,
                    payload=payload,
                    call_id=tool_call.call_id,
                )
                tool_run.metadata["success"] = True
                tool_run.end(
                    outputs={
                        "success": True,
                        "doc_count": doc_count,
                        "payload_keys": sorted(payload.keys()),
                    }
                )
                return result
            except Exception as exc:
                error_message = str(exc)
                tool_run.metadata.update(
                    {
                        "success": False,
                        "error": error_message,
                    }
                )
                tool_run.end(
                    outputs={
                        "success": False,
                        "error_type": type(exc).__name__,
                        "error": error_message,
                    }
                )
                return ToolResult(
                    name=tool_call.name,
                    success=False,
                    payload={},
                    call_id=tool_call.call_id,
                    error=error_message,
                )


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="search_notebook_context",
            description=(
                "按需搜索当前笔记本知识库，作为用户资料的辅助参考。"
                "只有用户要求参考 notebook、需要课程资料对照，或通用回答需要用户私有资料补充时才调用。"
            ),
            args_schema=NotebookSearchArgs,
            scope="qa",
            executor=search_notebook_context,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_session_summary",
            description="读取当前会话摘要，了解最近讲到哪、当前目标和未解决点。",
            args_schema=SessionSummaryArgs,
            scope="qa",
            executor=get_session_summary,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_user_learning_profile",
            description="读取用户长期学习画像，包括薄弱点、最近主题和错误统计。",
            args_schema=LearningProfileArgs,
            scope="qa",
            executor=get_user_learning_profile,
        )
    )
    registry.register(
        ToolDefinition(
            name="recommend_questions",
            description="根据当前用户与笔记本推荐适合继续练习的题目。",
            args_schema=RecommendQuestionsArgs,
            scope="qa",
            executor=recommend_questions,
        )
    )
    registry.register_external(
        name="mcp_web_search",
        description="使用外部 MCP 网页搜索获取最新资料、官网链接和外部参考页面。",
        args_schema=MCPWebSearchArgs,
        scope="qa",
        executor=mcp_web_search,
        availability=mcp_search_available,
    )
    registry.register_external(
        name="mcp_web_read",
        description="读取用户明确提供或本轮搜索返回的网页内容，并提取正文摘要。",
        args_schema=MCPWebReadArgs,
        scope="qa",
        executor=mcp_web_read,
        availability=mcp_read_available,
    )
    registry.register_external(
        name="tavily_web_search",
        description=(
            "通过 Tavily 实时搜索网络，获取最新、官网、文档、来源或权威外部事实。"
            "普通稳定概念不要默认搜索；遇到当前支持情况、版本、政策、MDN/官网解释或低置信外部事实时调用。"
        ),
        args_schema=TavilySearchArgs,
        scope="qa",
        executor=tavily_web_search,
        availability=tavily_available,
    )
    return registry


tool_registry = build_tool_registry()
tool_executor = ToolExecutor()
