"""
HTTP MCP Client
===============
以 fail-open 方式对接 HTTP MCP Server，并缓存远端 tool schema。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any

import requests
from loguru import logger

DEFAULT_MCP_TIMEOUT_SECONDS = 15
DEFAULT_MCP_MAX_RESULTS = 5
TOOLS_CACHE_TTL_SECONDS = 300
SUPPORTED_TRANSPORT = "http"

_CLIENT_LOCK = Lock()
_CLIENT_INSTANCE: "HTTPMCPClient | None" = None
_CLIENT_INITIALIZED = False
_RUNTIME_DISABLED = False
_TOOLS_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "definitions": {},
}


@dataclass(frozen=True)
class MCPSettings:
    enabled: bool
    transport: str
    server_url: str | None
    web_search_tool: str
    web_read_tool: str
    request_timeout_seconds: int
    max_results: int


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_mcp_settings() -> MCPSettings:
    transport = (os.getenv("MCP_TRANSPORT") or SUPPORTED_TRANSPORT).strip().lower()
    server_url = (os.getenv("MCP_WEB_SERVER_URL") or "").strip() or None
    timeout_raw = os.getenv("MCP_REQUEST_TIMEOUT_SECONDS")
    max_results_raw = os.getenv("MCP_MAX_RESULTS")

    try:
        timeout_seconds = max(3, int(timeout_raw or DEFAULT_MCP_TIMEOUT_SECONDS))
    except ValueError:
        timeout_seconds = DEFAULT_MCP_TIMEOUT_SECONDS

    try:
        max_results = max(1, min(10, int(max_results_raw or DEFAULT_MCP_MAX_RESULTS)))
    except ValueError:
        max_results = DEFAULT_MCP_MAX_RESULTS

    enabled = (
        _get_bool_env("MCP_ENABLED", default=False)
        and transport == SUPPORTED_TRANSPORT
        and bool(server_url)
    )
    return MCPSettings(
        enabled=enabled,
        transport=transport,
        server_url=server_url,
        web_search_tool=(os.getenv("MCP_WEB_SEARCH_TOOL") or "web_search").strip(),
        web_read_tool=(os.getenv("MCP_WEB_READ_TOOL") or "web_read").strip(),
        request_timeout_seconds=timeout_seconds,
        max_results=max_results,
    )


def reset_mcp_client_cache() -> None:
    global _CLIENT_INSTANCE, _CLIENT_INITIALIZED, _RUNTIME_DISABLED
    with _CLIENT_LOCK:
        _CLIENT_INSTANCE = None
        _CLIENT_INITIALIZED = False
        _RUNTIME_DISABLED = False
        _TOOLS_CACHE["expires_at"] = 0.0
        _TOOLS_CACHE["definitions"] = {}


class HTTPMCPClient:
    def __init__(self, settings: MCPSettings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self._handshake_done = False

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        if not self.settings.server_url:
            raise RuntimeError("未配置 MCP_WEB_SERVER_URL")
        response = self.session.post(
            self.settings.server_url,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
            headers={"Accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()
        return response

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        response = self._post(payload)
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(message or f"MCP {method} 调用失败")
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        try:
            self._post(payload)
        except Exception:
            return

    def initialize(self) -> None:
        if self._handshake_done:
            return

        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "learning-assistant",
                    "version": "0.1.0",
                },
                "capabilities": {},
            },
        )
        self._notify("notifications/initialized", {})
        self._handshake_done = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._rpc("tools/list", {})
        if isinstance(result, dict):
            tools = result.get("tools", [])
        elif isinstance(result, list):
            tools = result
        else:
            tools = []
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict):
            return result
        return {"content": result}


def _disable_runtime(reason: str) -> None:
    global _RUNTIME_DISABLED
    if not _RUNTIME_DISABLED:
        logger.warning(f"⚠️ MCP 已降级关闭: {reason}")
    _RUNTIME_DISABLED = True


def get_client() -> HTTPMCPClient | None:
    global _CLIENT_INSTANCE, _CLIENT_INITIALIZED
    settings = get_mcp_settings()
    if _RUNTIME_DISABLED or not settings.enabled:
        return None

    with _CLIENT_LOCK:
        if _CLIENT_INITIALIZED:
            return _CLIENT_INSTANCE

        _CLIENT_INITIALIZED = True
        try:
            _CLIENT_INSTANCE = HTTPMCPClient(settings)
        except Exception as exc:
            _CLIENT_INSTANCE = None
            _disable_runtime(str(exc))
        return _CLIENT_INSTANCE


def initialize_mcp() -> bool:
    settings = get_mcp_settings()
    if not _get_bool_env("MCP_ENABLED", default=False):
        logger.info("ℹ️ MCP 外部工具已关闭（MCP_ENABLED=false）")
        return False
    if not settings.server_url:
        logger.warning("⚠️ MCP 已开启，但未配置 MCP_WEB_SERVER_URL，已跳过")
        return False
    if settings.transport != SUPPORTED_TRANSPORT:
        logger.warning(f"⚠️ 当前仅支持 HTTP MCP，已忽略 transport={settings.transport}")
        return False

    try:
        definitions = load_tool_definitions(force_refresh=True)
    except Exception as exc:
        _disable_runtime(str(exc))
        return False

    logger.info(
        "✅ MCP 外部工具已启用 | "
        f"server={settings.server_url} | "
        f"tools={', '.join(sorted(definitions.keys())) or 'none'}"
    )
    return True


def load_tool_definitions(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    settings = get_mcp_settings()
    if _RUNTIME_DISABLED or not settings.enabled:
        return {}

    now = time.time()
    if (
        not force_refresh
        and _TOOLS_CACHE["definitions"]
        and now < float(_TOOLS_CACHE["expires_at"])
    ):
        return dict(_TOOLS_CACHE["definitions"])

    client = get_client()
    if client is None:
        return {}

    try:
        tools = client.list_tools()
    except Exception as exc:
        _disable_runtime(str(exc))
        return {}

    definitions = {
        str(tool.get("name", "")).strip(): dict(tool)
        for tool in tools
        if str(tool.get("name", "")).strip()
    }
    _TOOLS_CACHE["definitions"] = dict(definitions)
    _TOOLS_CACHE["expires_at"] = now + TOOLS_CACHE_TTL_SECONDS
    return dict(definitions)


def is_tool_available(tool_name: str) -> bool:
    if not tool_name:
        return False
    return tool_name in load_tool_definitions()


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise RuntimeError("MCP 当前不可用")
    return client.call_tool(name, arguments)


def _parse_json_text_blob(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None


def _extract_structured_content(payload: dict[str, Any]) -> Any:
    structured = payload.get("structuredContent")
    if structured:
        return structured

    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "json" and isinstance(item.get("json"), (dict, list)):
                return item.get("json")
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parsed = _parse_json_text_blob(item["text"])
                if parsed is not None:
                    return parsed
    elif isinstance(content, str):
        parsed = _parse_json_text_blob(content)
        if parsed is not None:
            return parsed
    return None


def _extract_text_content(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
            else:
                text = str(item)
            text = str(text).strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def normalize_search_payload(
    payload: dict[str, Any],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    structured = _extract_structured_content(payload)
    candidates: list[Any] = []

    if isinstance(structured, dict):
        for key in ("results", "items", "documents", "links", "pages"):
            value = structured.get(key)
            if isinstance(value, list):
                candidates = value
                break
    elif isinstance(structured, list):
        candidates = structured

    if not candidates:
        text_content = _extract_text_content(payload)
        parsed = _parse_json_text_blob(text_content)
        if isinstance(parsed, dict):
            for key in ("results", "items", "documents", "links", "pages"):
                value = parsed.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
        elif isinstance(parsed, list):
            candidates = parsed

    normalized: list[dict[str, Any]] = []
    for raw_item in candidates[:max_results]:
        if not isinstance(raw_item, dict):
            continue
        url = str(raw_item.get("url") or raw_item.get("link") or "").strip()
        title = str(raw_item.get("title") or raw_item.get("name") or url or "网页结果").strip()
        snippet = str(
            raw_item.get("snippet")
            or raw_item.get("summary")
            or raw_item.get("description")
            or raw_item.get("content")
            or raw_item.get("text")
            or ""
        ).strip()
        source = str(raw_item.get("source") or raw_item.get("site") or "mcp:web_search").strip()
        if not url and not snippet:
            continue
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
            }
        )
    return normalized


def normalize_read_payload(
    payload: dict[str, Any],
    *,
    fallback_url: str,
) -> dict[str, Any]:
    structured = _extract_structured_content(payload)
    text_content = _extract_text_content(payload)

    if isinstance(structured, dict):
        title = str(structured.get("title") or structured.get("name") or fallback_url).strip()
        url = str(structured.get("url") or structured.get("link") or fallback_url).strip()
        content = str(
            structured.get("content")
            or structured.get("text")
            or structured.get("markdown")
            or structured.get("summary")
            or text_content
        ).strip()
        source = str(structured.get("source") or "mcp:web_read").strip()
    else:
        title = fallback_url
        url = fallback_url
        content = text_content
        source = "mcp:web_read"

    return {
        "title": title,
        "url": url,
        "content": content[:2400],
        "source": source,
    }
