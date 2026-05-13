from __future__ import annotations

import hashlib
import time
from typing import Any

from loguru import logger

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
    started_at = time.perf_counter()
    query_hash = hashlib.sha256(safe_query.encode("utf-8")).hexdigest()[:12]
    logger.info(
        "🌐 MCP WebSearch 开始 | tool={} query_len={} query_hash={} max_results={}",
        settings.web_search_tool,
        len(safe_query),
        query_hash,
        max_results,
    )
    try:
        raw_payload = call_mcp_tool(
            settings.web_search_tool,
            {
                "query": safe_query,
                "max_results": max_results,
            },
        )
        items = normalize_search_payload(raw_payload, max_results=max_results)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "🌐 MCP WebSearch 失败 | tool={} query_hash={} elapsed_ms={} reason={}",
            settings.web_search_tool,
            query_hash,
            elapsed_ms,
            exc.__class__.__name__,
        )
        raise
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "🌐 MCP WebSearch 完成 | tool={} query_hash={} doc_count={} elapsed_ms={}",
        settings.web_search_tool,
        query_hash,
        len(items),
        elapsed_ms,
    )
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
