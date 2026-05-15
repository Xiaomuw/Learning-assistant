from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping


_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def build_trace_record(stage: str, **payload: Any) -> dict[str, Any]:
    """Build a small, serializable trace record for graph decisions.

    Trace records are intended for diagnostics and regression assertions. Keep
    them compact and avoid raw prompts, headers, secrets, external payloads, or
    full answer text.
    """

    record: dict[str, Any] = {"stage": stage}
    for key, value in payload.items():
        record[key] = _sanitize_trace_value(value)
    return record


def append_trace_record(state: Mapping[str, Any], stage: str, **payload: Any) -> list[dict[str, Any]]:
    records = [item for item in list(state.get("trace_records") or []) if isinstance(item, dict)]
    records.append(build_trace_record(stage, **payload))
    return records


def _sanitize_trace_value(value: Any) -> Any:
    if isinstance(value, _SAFE_SCALAR_TYPES):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _looks_sensitive_key(key_text):
                continue
            sanitized[key_text] = _sanitize_trace_value(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_trace_value(item) for item in value[:20]]
    return str(value)


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("token", "secret", "password", "authorization", "api_key", "apikey"))
