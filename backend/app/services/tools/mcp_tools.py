from __future__ import annotations

from typing import Any

from app.infrastructure.mcp import (
    build_external_query,
    call_tool as call_mcp_tool,
    extract_urls,
    get_mcp_settings,
    is_tool_available,
    normalize_read_payload,
    normalize_search_payload,
)
from app.shared.schemas.qa_runtime import AgentRequest


def remember_mcp_urls(agent_request: AgentRequest, urls: list[str]) -> None:
    remembered = set(agent_request.runtime_context.get("mcp_allowed_urls", []) or [])
    remembered.update(urls)
    agent_request.runtime_context["mcp_allowed_urls"] = sorted(remembered)


def can_read_mcp_url(agent_request: AgentRequest, url: str) -> bool:
    if not url:
        return False
    explicit_urls = set(extract_urls(agent_request.question))
    remembered = set(agent_request.runtime_context.get("mcp_allowed_urls", []) or [])
    return url in explicit_urls or url in remembered


def mcp_search_available(_agent_request: AgentRequest) -> bool:
    settings = get_mcp_settings()
    if not settings.enabled:
        return False
    return is_tool_available(settings.web_search_tool)


def mcp_read_available(_agent_request: AgentRequest) -> bool:
    settings = get_mcp_settings()
    if not settings.enabled:
        return False
    return is_tool_available(settings.web_read_tool)


def mcp_web_search(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    settings = get_mcp_settings()
    if not settings.enabled:
        raise RuntimeError("MCP 外部工具未启用")

    requested_query = str(args.get("query", "") or "").strip()
    max_results = int(args.get("max_results", settings.max_results) or settings.max_results)
    max_results = max(1, min(max_results, settings.max_results))
    safe_query = build_external_query(
        question=agent_request.question,
        active_topic=str(agent_request.session_memory.get("active_topic", "") or ""),
        requested_query=requested_query,
    )
    raw_payload = call_mcp_tool(
        settings.web_search_tool,
        {
            "query": safe_query,
            "max_results": max_results,
        },
    )
    items = normalize_search_payload(raw_payload, max_results=max_results)
    remembered_urls = [item["url"] for item in items if item.get("url")]
    remember_mcp_urls(agent_request, remembered_urls)
    return {
        "query": safe_query,
        "doc_count": len(items),
        "results": items,
        "documents": [
            {
                "content": item.get("snippet", "")[:800],
                "metadata": {
                    "source": item.get("source", "mcp:web_search"),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "tool": "mcp_web_search",
                    "is_external": True,
                },
                "distance": 0.0,
            }
            for item in items
        ],
        "allowed_urls": remembered_urls,
    }


def mcp_web_read(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    settings = get_mcp_settings()
    if not settings.enabled:
        raise RuntimeError("MCP 外部工具未启用")

    url = str(args.get("url", "") or "").strip()
    if not can_read_mcp_url(agent_request, url):
        raise RuntimeError("只允许读取用户明确提供或本轮搜索返回的 URL")

    raw_payload = call_mcp_tool(settings.web_read_tool, {"url": url})
    page = normalize_read_payload(raw_payload, fallback_url=url)
    remember_mcp_urls(agent_request, [page["url"]])
    return {
        "url": page["url"],
        "title": page["title"],
        "content": page["content"],
        "documents": [
            {
                "content": page["content"][:1600],
                "metadata": {
                    "source": page.get("source", "mcp:web_read"),
                    "title": page.get("title", ""),
                    "url": page.get("url", url),
                    "tool": "mcp_web_read",
                    "is_external": True,
                },
                "distance": 0.0,
            }
        ],
    }
