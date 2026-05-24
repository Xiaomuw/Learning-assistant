"""
Safe structured-output helper.

Some OpenAI-compatible endpoints support normal chat completions but reject
LangChain's native structured-output request shape. This helper keeps native
structured output where the model profile allows it, then falls back to a plain
JSON prompt/parser path without changing the public API.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel

from app.infrastructure.llm.profile import get_model_profile

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def message_to_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
            else:
                text = str(item)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def extract_json_text(raw: Any) -> str:
    """Extract the first JSON object/array from an LLM response."""
    text = _strip_json_fence(message_to_text(raw))
    if not text:
        raise ValueError("模型没有返回可解析内容")

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        raise ValueError("模型输出中没有 JSON 对象")

    start = min(starts)
    stack: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                continue
            stack.pop()
            if not stack:
                candidate = text[start : index + 1]
                json.loads(candidate)
                return candidate

    raise ValueError("模型输出中的 JSON 不完整")


def validate_schema_output(raw: Any, schema: type[SchemaT]) -> SchemaT:
    if isinstance(raw, schema):
        return raw
    if hasattr(raw, "content"):
        return validate_schema_output(message_to_text(raw), schema)
    if isinstance(raw, BaseModel):
        return schema.model_validate(raw.model_dump())
    if isinstance(raw, (dict, list)):
        return schema.model_validate(raw)

    json_text = extract_json_text(raw)
    return schema.model_validate_json(json_text)


def invoke_with_schema(
    prompt: Any,
    llm: Any,
    schema: type[SchemaT],
    payload: dict[str, Any],
    *,
    model_name: str | None = None,
    prefer_native: bool = True,
) -> SchemaT:
    """Invoke a prompt and return a validated Pydantic schema.

    Native structured output is used only when the model profile says it is
    safe. If native invocation fails, the helper retries once as plain chat and
    parses JSON from the response.
    """
    profile = get_model_profile(model_name)
    if prefer_native and profile.supports_structured_output:
        try:
            result = (prompt | llm.with_structured_output(schema)).invoke(payload)
            return validate_schema_output(result, schema)
        except Exception as exc:
            logger.warning(
                f"⚠️ native structured output 失败，改走 JSON 文本解析: {exc}"
            )

    result = (prompt | llm).invoke(payload)
    return validate_schema_output(result, schema)
