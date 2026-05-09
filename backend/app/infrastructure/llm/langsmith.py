"""
LangSmith Observability
=======================
统一管理 LangSmith tracing 的配置、初始化与上下文包装。
"""

from __future__ import annotations

import os
import re
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator
from urllib.parse import urlparse

from loguru import logger

try:
    import langsmith as ls
    from langsmith import Client
    from langsmith.run_helpers import tracing_context
except Exception:  # pragma: no cover - 兼容缺失依赖环境
    ls = None
    Client = None
    tracing_context = None


DEFAULT_LANGSMITH_PROJECT = "learning-assistant"
_CLIENT_LOCK = Lock()
_CLIENT_INITIALIZED = False
_CLIENT_INSTANCE: Client | None = None
_CLIENT_FAILURE_LOGGED = False
_RUNTIME_DISABLED = False

_MAX_TRACE_STRING_CHARS = 500
_MAX_TRACE_LIST_ITEMS = 2
_MAX_TRACE_DEPTH = 6
_FULL_CONTENT_KEYS = {
    "question",
    "user_message",
    "answer",
    "final_answer",
    "model_answer",
    "response",
    "reasoning_summary",
    "safe_reasoning_summary",
    "safe_decision_summary",
    "stem",
    "explanation",
    "selected_option",
    "correct_option",
}
_HIDDEN_REASONING_KEYS = {
    "reasoning_content",
    "raw_reasoning",
    "chain_of_thought",
    "cot",
    "raw_cot",
    "thinking_trace",
    "internal_reasoning",
}
_HIDDEN_REASONING_TYPES = {"reasoning", "thinking", "reasoning_content"}

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|access[_-]?key|secret|token|password|authorization|cookie|credential)",
    re.IGNORECASE,
)
_LONG_TEXT_KEYS = {
    "short_term_context",
    "session_memory_context",
    "long_term_context",
    "notebook_context",
    "user_style_prompt",
    "prompt",
    "system_prompt",
}
_DOCUMENT_LIST_KEYS = {
    "raw_retrieved_docs",
    "verified_context",
    "retrieved_docs",
    "documents",
    "quiz_rag_docs",
}
_MESSAGE_LIST_KEYS = {
    "messages",
    "conversation",
    "short_term_messages",
}
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_TOKEN_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|lsv2_[A-Za-z0-9_-]{20,}|doo_v1_[A-Za-z0-9_-]{20,})\b"
)
_DB_PASSWORD_PATTERN = re.compile(
    r"(?P<prefix>(?:postgres(?:ql)?|mysql|redis)(?:\+\w+)?://[^:\s/@]+:)(?P<password>[^@\s]+)(?P<suffix>@)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LangSmithSettings:
    enabled: bool
    configured: bool
    project: str
    endpoint: str | None
    has_api_key: bool
    sdk_available: bool


class NullRun:
    """在 tracing 关闭时作为 no-op 占位。"""

    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.tags: list[str] = []

    def end(self, *args: Any, **kwargs: Any) -> None:
        return None


class SafeTraceRun(NullRun):
    """包装真实 RunTree，避免 end() 异常打断主流程。"""

    def __init__(self, run_tree: Any) -> None:
        self._run_tree = run_tree
        self.metadata = getattr(run_tree, "metadata", {})
        self.tags = getattr(run_tree, "tags", [])

    def end(self, *args: Any, **kwargs: Any) -> None:
        try:
            self._run_tree.end(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - 依赖外部服务异常
            logger.warning(f"⚠️ LangSmith run end 失败，已忽略: {exc}")


def _redact_text(value: str, *, max_chars: int | None = _MAX_TRACE_STRING_CHARS) -> str:
    redacted = _DB_PASSWORD_PATTERN.sub(r"\g<prefix><redacted>\g<suffix>", value)
    redacted = _TOKEN_PATTERN.sub("<redacted-token>", redacted)
    redacted = _EMAIL_PATTERN.sub("<redacted-email>", redacted)
    redacted = _UUID_PATTERN.sub("<redacted-uuid>", redacted)
    if max_chars is not None and len(redacted) > max_chars:
        overflow = len(redacted) - max_chars
        redacted = f"{redacted[:max_chars]}... [truncated {overflow} chars]"
    return redacted


def _summarize_text(value: str) -> dict[str, Any]:
    return {
        "char_count": len(value),
        "preview": _redact_text(value),
    }


def _summarize_sequence(
    value: list[Any] | tuple[Any, ...],
    *,
    key: str,
    depth: int,
) -> dict[str, Any]:
    preview = [
        sanitize_for_langsmith(item, key=key, depth=depth - 1)
        for item in list(value)[:_MAX_TRACE_LIST_ITEMS]
    ]
    return {
        "count": len(value),
        "preview": preview,
    }


def _hidden_reasoning_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        char_count = len(value)
    elif isinstance(value, (list, tuple)):
        char_count = sum(len(str(item)) for item in value)
    elif isinstance(value, dict):
        char_count = sum(len(str(item_value)) for item_value in value.values())
    else:
        char_count = len(str(value))
    return {
        "redacted": True,
        "char_count": char_count,
        "reason": "raw reasoning_content is not sent to LangSmith; use safe reasoning summaries instead",
    }


def sanitize_for_langsmith(
    value: Any,
    *,
    key: str = "",
    depth: int = _MAX_TRACE_DEPTH,
) -> Any:
    """Return a compact, redacted shape safe to send to LangSmith."""
    if depth <= 0:
        return "<truncated-depth>"

    normalized_key = key.lower()
    if normalized_key in _HIDDEN_REASONING_KEYS:
        return _hidden_reasoning_summary(value)
    if normalized_key and _SENSITIVE_KEY_PATTERN.search(normalized_key):
        return "<redacted>"

    if isinstance(value, str):
        if normalized_key in _FULL_CONTENT_KEYS:
            return _redact_text(value, max_chars=None)
        if normalized_key in _LONG_TEXT_KEYS:
            return _summarize_text(value)
        return _redact_text(value)

    if isinstance(value, dict):
        item_type = str(value.get("type") or "").strip().lower()
        if item_type in _HIDDEN_REASONING_TYPES:
            return {
                "type": item_type,
                **_hidden_reasoning_summary(value),
            }
        if normalized_key in {"metadata", "guard", "learning_context", "context_audit", "retrieval_diagnosis"}:
            return {
                str(item_key): sanitize_for_langsmith(item_value, key=str(item_key), depth=depth - 1)
                for item_key, item_value in value.items()
            }
        return {
            str(item_key): sanitize_for_langsmith(item_value, key=str(item_key), depth=depth - 1)
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple)):
        if normalized_key in _DOCUMENT_LIST_KEYS or normalized_key in _MESSAGE_LIST_KEYS:
            return _summarize_sequence(value, key=normalized_key, depth=depth)
        if len(value) > _MAX_TRACE_LIST_ITEMS:
            return _summarize_sequence(value, key=normalized_key, depth=depth)
        return [
            sanitize_for_langsmith(item, key=normalized_key, depth=depth - 1)
            for item in value
        ]

    return value


def sanitize_langsmith_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return sanitize_for_langsmith(inputs)


def sanitize_langsmith_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    return sanitize_for_langsmith(outputs)


def sanitize_langsmith_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return sanitize_for_langsmith(metadata)


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_langsmith_environment() -> None:
    """Keep empty local .env values from confusing LangChain auto tracing."""
    for endpoint_name in ("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"):
        if not (os.getenv(endpoint_name) or "").strip():
            os.environ.pop(endpoint_name, None)
    tracing_enabled = _get_bool_env("LANGSMITH_TRACING", default=False)
    api_key = (os.getenv("LANGSMITH_API_KEY") or "").strip()
    endpoint = (os.getenv("LANGSMITH_ENDPOINT") or "").strip()
    project = (os.getenv("LANGSMITH_PROJECT") or "").strip() or DEFAULT_LANGSMITH_PROJECT

    if not tracing_enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    if not api_key:
        os.environ.pop("LANGSMITH_TRACING", None)
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        return

    # LangChain/LangGraph integrations still read the older LANGCHAIN_* names.
    # Keep them aligned with the product-level LANGSMITH_* configuration so
    # automatic child runs land in the same project as our explicit trace_run calls.
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGCHAIN_API_KEY"] = api_key
    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint


_normalize_langsmith_environment()


def get_langsmith_settings() -> LangSmithSettings:
    _normalize_langsmith_environment()
    api_key = (os.getenv("LANGSMITH_API_KEY") or "").strip()
    endpoint = (os.getenv("LANGSMITH_ENDPOINT") or "").strip() or None
    project = (os.getenv("LANGSMITH_PROJECT") or "").strip() or DEFAULT_LANGSMITH_PROJECT
    tracing_enabled = _get_bool_env("LANGSMITH_TRACING", default=False)
    sdk_available = Client is not None and tracing_context is not None and ls is not None
    configured = sdk_available and bool(api_key)
    return LangSmithSettings(
        enabled=tracing_enabled and configured,
        configured=configured,
        project=project,
        endpoint=endpoint,
        has_api_key=bool(api_key),
        sdk_available=sdk_available,
    )


def reset_langsmith_client_cache() -> None:
    global _CLIENT_INITIALIZED, _CLIENT_INSTANCE, _CLIENT_FAILURE_LOGGED, _RUNTIME_DISABLED
    with _CLIENT_LOCK:
        _CLIENT_INITIALIZED = False
        _CLIENT_INSTANCE = None
        _CLIENT_FAILURE_LOGGED = False
        _RUNTIME_DISABLED = False


def get_langsmith_client() -> Client | None:
    global _CLIENT_INITIALIZED, _CLIENT_INSTANCE, _CLIENT_FAILURE_LOGGED

    settings = get_langsmith_settings()
    if _RUNTIME_DISABLED or not settings.enabled or Client is None:
        return None

    with _CLIENT_LOCK:
        if _CLIENT_INITIALIZED:
            return _CLIENT_INSTANCE

        _CLIENT_INITIALIZED = True
        try:
            _CLIENT_INSTANCE = Client(
                api_key=os.getenv("LANGSMITH_API_KEY"),
                api_url=settings.endpoint,
                hide_inputs=sanitize_langsmith_inputs,
                hide_outputs=sanitize_langsmith_outputs,
                hide_metadata=sanitize_langsmith_metadata,
            )
        except Exception as exc:  # pragma: no cover - 极端初始化失败
            _CLIENT_INSTANCE = None
            if not _CLIENT_FAILURE_LOGGED:
                logger.warning(f"⚠️ LangSmith Client 初始化失败，已降级关闭 tracing: {exc}")
                _CLIENT_FAILURE_LOGGED = True
        return _CLIENT_INSTANCE


def initialize_langsmith() -> bool:
    settings = get_langsmith_settings()
    if _RUNTIME_DISABLED:
        logger.warning("⚠️ LangSmith tracing 已在当前进程中降级关闭")
        return False
    if not _get_bool_env("LANGSMITH_TRACING", default=False):
        logger.info("ℹ️ LangSmith tracing 已关闭（LANGSMITH_TRACING=false）")
        return False

    if not settings.sdk_available:
        logger.warning("⚠️ LangSmith SDK 不可用，已降级为无 tracing 模式")
        return False

    if not settings.has_api_key:
        logger.warning("⚠️ 未配置 LANGSMITH_API_KEY，已降级为无 tracing 模式")
        return False

    client = get_langsmith_client()
    if client is None:
        logger.warning("⚠️ LangSmith client 不可用，已降级为无 tracing 模式")
        return False

    logger.info(
        "✅ LangSmith tracing 已启用 | "
        f"project={settings.project} | endpoint={settings.endpoint or 'cloud-default'}"
    )
    return True


def get_langsmith_health_status() -> dict[str, Any]:
    """Return a readable LangSmith readiness summary without breaking startup."""

    settings = get_langsmith_settings()
    endpoint = settings.endpoint or "https://api.smith.langchain.com"
    base = {
        "project": settings.project,
        "endpoint": endpoint,
        "has_api_key": settings.has_api_key,
        "sdk_available": settings.sdk_available,
        "langchain_tracing_v2": os.getenv("LANGCHAIN_TRACING_V2") == "true",
        "langchain_project": os.getenv("LANGCHAIN_PROJECT") or "",
        "langchain_endpoint": os.getenv("LANGCHAIN_ENDPOINT") or "",
    }
    if not _get_bool_env("LANGSMITH_TRACING", default=False):
        return {
            **base,
            "status": "disabled",
            "enabled": False,
            "client_ready": False,
        }
    if not settings.sdk_available:
        return {
            **base,
            "status": "sdk_unavailable",
            "enabled": False,
            "client_ready": False,
        }
    if not settings.has_api_key:
        return {
            **base,
            "status": "missing_api_key",
            "enabled": False,
            "client_ready": False,
        }
    host = urlparse(endpoint).hostname or endpoint
    try:
        socket.getaddrinfo(host, 443)
    except Exception as exc:  # pragma: no cover - depends on local DNS/network
        return {
            **base,
            "status": "dns_unreachable",
            "enabled": True,
            "host": host,
            "client_ready": False,
            "error_type": exc.__class__.__name__,
        }
    client = get_langsmith_client()
    if client is None:
        return {
            **base,
            "status": "client_unavailable",
            "enabled": True,
            "host": host,
            "client_ready": False,
        }
    return {
        **base,
        "status": "client_ready",
        "enabled": True,
        "host": host,
        "client_ready": True,
    }


@contextmanager
def qa_tracing_context(
    *,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Iterator[None]:
    global _RUNTIME_DISABLED
    settings = get_langsmith_settings()
    client = get_langsmith_client()

    if _RUNTIME_DISABLED or not settings.enabled or client is None or tracing_context is None:
        yield
        return

    manager = tracing_context(
        enabled=True,
        project_name=settings.project,
        metadata=dict(metadata or {}),
        tags=list(tags or []),
        client=client,
    )
    try:
        manager.__enter__()
    except Exception as exc:  # pragma: no cover - 依赖外部服务异常
        logger.warning(f"⚠️ LangSmith tracing context 启动失败，已降级继续执行: {exc}")
        _RUNTIME_DISABLED = True
        yield
        return

    exc_type = exc = tb = None
    try:
        yield
    except BaseException as caught_exc:  # pragma: no cover - 仅在真实异常路径触发
        exc_type = type(caught_exc)
        exc = caught_exc
        tb = caught_exc.__traceback__
        raise
    finally:
        try:
            manager.__exit__(exc_type, exc, tb)
        except Exception as exc:  # pragma: no cover - 依赖外部服务异常
            logger.warning(f"⚠️ LangSmith tracing context 关闭失败，已忽略: {exc}")
            _RUNTIME_DISABLED = True


@contextmanager
def trace_run(
    *,
    name: str,
    run_type: str = "chain",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Iterator[NullRun | Any]:
    global _RUNTIME_DISABLED
    settings = get_langsmith_settings()
    client = get_langsmith_client()

    if _RUNTIME_DISABLED or not settings.enabled or client is None or ls is None:
        yield NullRun()
        return

    manager = ls.trace(
        name=name,
        run_type=run_type,
        inputs=dict(inputs or {}),
        metadata=dict(metadata or {}),
        tags=list(tags or []),
        project_name=settings.project,
        client=client,
    )
    try:
        run_tree = manager.__enter__()
    except Exception as exc:  # pragma: no cover - 依赖外部服务异常
        logger.warning(f"⚠️ LangSmith trace '{name}' 启动失败，已降级继续执行: {exc}")
        _RUNTIME_DISABLED = True
        yield NullRun()
        return

    exc_type = exc = tb = None
    try:
        yield SafeTraceRun(run_tree)
    except BaseException as caught_exc:  # pragma: no cover - 仅在真实异常路径触发
        exc_type = type(caught_exc)
        exc = caught_exc
        tb = caught_exc.__traceback__
        raise
    finally:
        try:
            manager.__exit__(exc_type, exc, tb)
        except Exception as exc:  # pragma: no cover - 依赖外部服务异常
            logger.warning(f"⚠️ LangSmith trace '{name}' 关闭失败，已忽略: {exc}")
            _RUNTIME_DISABLED = True
