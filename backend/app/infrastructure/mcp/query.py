"""
MCP Query Helpers
=================
负责外部 MCP 查询词构造与 URL 提取，避免把完整上下文直接发送到外部工具。
"""

from __future__ import annotations

import re

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
MAX_EXTERNAL_QUERY_LENGTH = 220


def _normalize_whitespace(value: str) -> str:
    return " ".join((value or "").split()).strip()


def extract_urls(text: str) -> list[str]:
    """提取文本中的显式 URL，仅用于允许读取用户明确提供的页面。"""
    if not text:
        return []
    results: list[str] = []
    for match in URL_PATTERN.findall(text):
        candidate = match.rstrip(".,;:!?)>]}\"'")
        if candidate.startswith("http://") or candidate.startswith("https://"):
            if candidate not in results:
                results.append(candidate)
    return results


def build_external_query(
    *,
    question: str,
    active_topic: str = "",
    requested_query: str = "",
    max_length: int = MAX_EXTERNAL_QUERY_LENGTH,
) -> str:
    """
    为外部 MCP 网页搜索构造精简查询词。

    只使用用户问题、模型给出的必要关键词与会话主主题，不拼接完整 notebook/长期记忆。
    """
    base = _normalize_whitespace(requested_query or question)
    topic = _normalize_whitespace(active_topic)

    if topic and topic.lower() not in base.lower():
        base = f"{base} {topic}".strip()

    if len(base) > max_length:
        base = base[:max_length].rsplit(" ", 1)[0].strip() or base[:max_length].strip()

    return base
