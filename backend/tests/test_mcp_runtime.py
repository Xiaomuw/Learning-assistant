from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.qa.capability_tools import WEB_EXTRACT, WEB_SEARCH, tool_executor, tool_registry
from app.infrastructure.mcp.client import get_mcp_settings, reset_mcp_client_cache
from app.infrastructure.mcp.query import build_external_query
from app.domains.qa.schemas import AgentRequest, ToolCall


class MCPRuntimeTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_mcp_client_cache()
        for key in (
            "MCP_ENABLED",
            "MCP_TRANSPORT",
            "MCP_WEB_SERVER_URL",
            "MCP_WEB_SEARCH_TOOL",
            "MCP_WEB_READ_TOOL",
            "MCP_REQUEST_TIMEOUT_SECONDS",
            "MCP_MAX_RESULTS",
        ):
            os.environ.pop(key, None)

    def test_build_external_query_uses_question_and_active_topic_only(self) -> None:
        query = build_external_query(
            question="请帮我查一下 Python asyncio 最新官方文档",
            active_topic="异步编程",
            requested_query="asyncio 官方文档 最新",
        )

        self.assertIn("asyncio 官方文档 最新", query)
        self.assertIn("异步编程", query)
        self.assertLessEqual(len(query), 220)

    def test_mcp_settings_disabled_without_server_url(self) -> None:
        os.environ["MCP_ENABLED"] = "true"
        settings = get_mcp_settings()
        self.assertFalse(settings.enabled)

    def test_capability_registry_is_deny_by_default_without_policy(self) -> None:
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="请帮我搜索 Python asyncio 官方文档",
            question_type="concept",
        )

        tools = tool_registry.get_available_tools(scope="qa", agent_request=request)

        self.assertEqual(tools, [])

    def test_capability_registry_includes_mcp_capabilities_when_policy_allows(self) -> None:
        os.environ["MCP_ENABLED"] = "true"
        os.environ["MCP_WEB_SERVER_URL"] = "https://example.com/mcp"
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="请帮我搜索 Python asyncio 官方文档",
            question_type="concept",
            runtime_context={"allow_tools": True, "allow_search": True},
        )

        with patch(
            "app.services.tools.mcp_tools.is_tool_available",
            side_effect=lambda name: name in {"web_search", "web_read"},
        ):
            tools = tool_registry.get_available_tools(scope="qa", agent_request=request)

        tool_names = {tool.name for tool in tools}
        self.assertIn(WEB_SEARCH, tool_names)
        self.assertIn(WEB_EXTRACT, tool_names)

    def test_mcp_web_search_normalizes_results(self) -> None:
        os.environ["MCP_ENABLED"] = "true"
        os.environ["MCP_WEB_SERVER_URL"] = "https://example.com/mcp"
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="帮我查一下 asyncio 官方文档",
            question_type="concept",
            session_memory={"active_topic": "异步编程"},
            runtime_context={"allow_tools": True, "allow_search": True},
        )

        with (
            patch("app.domains.qa.capability_tools.tavily_available", return_value=False),
            patch(
                "app.services.tools.mcp_tools.is_tool_available",
                side_effect=lambda name: name == "web_search",
            ),
            patch(
                "app.services.tools.mcp_tools.call_mcp_tool",
                return_value={
                    "structuredContent": {
                        "results": [
                            {
                                "title": "Python asyncio docs",
                                "url": "https://docs.python.org/3/library/asyncio.html",
                                "snippet": "asyncio 是 Python 的异步 IO 标准库。",
                                "source": "python-docs",
                            }
                        ]
                    }
                },
            ),
        ):
            result = tool_executor.execute(
                ToolCall(name=WEB_SEARCH, args={"query": "asyncio 官方文档", "max_results": 3}),
                agent_request=request,
            )

        self.assertTrue(result.success)
        self.assertEqual(result.payload["doc_count"], 1)
        self.assertEqual(result.payload["_tool_capability"], WEB_SEARCH)
        self.assertEqual(result.payload["_tool_provider"], "mcp")
        self.assertEqual(result.payload["documents"][0]["metadata"]["retrieval_source"], "web")
        self.assertIn("https://docs.python.org", request.runtime_context["mcp_allowed_urls"][0])

    def test_mcp_web_read_rejects_unknown_url(self) -> None:
        os.environ["MCP_ENABLED"] = "true"
        os.environ["MCP_WEB_SERVER_URL"] = "https://example.com/mcp"
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="帮我看看这个主题",
            question_type="concept",
        )

        with patch("app.services.tools.mcp_tools.call_mcp_tool") as mock_call:
            result = tool_executor.execute(
                ToolCall(name=WEB_EXTRACT, args={"url": "https://example.com/secret"}),
                agent_request=request,
            )

        self.assertFalse(result.success)
        self.assertIn("只允许读取用户明确提供", result.error)
        mock_call.assert_not_called()
