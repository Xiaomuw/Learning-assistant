"""Small text cleanup helpers for model outputs.

The product renders Q&A answers as structured cards, so model fields should be
plain text instead of Markdown snippets that leak formatting markers into the UI.
"""

from __future__ import annotations

import re

_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_EMPHASIS_PATTERN = re.compile(r"(\*\*|__|\*|_)")
_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+")
_QUOTE_PATTERN = re.compile(r"^\s*>\s?")
_HORIZONTAL_RULE_PATTERN = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")


def strip_markdown_artifacts(value: str) -> str:
    """Remove common Markdown markers while keeping the readable content."""

    text = str(value or "")
    if not text.strip():
        return ""

    text = _LINK_PATTERN.sub(r"\1", text)
    text = _INLINE_CODE_PATTERN.sub(r"\1", text)
    text = _EMPHASIS_PATTERN.sub("", text)

    cleaned_lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or _HORIZONTAL_RULE_PATTERN.match(line):
            continue
        line = _HEADING_PATTERN.sub("", line)
        line = _BULLET_PATTERN.sub("", line)
        line = _QUOTE_PATTERN.sub("", line)
        cleaned_lines.append(line.strip())

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_markdown_list(values: list[str]) -> list[str]:
    return [cleaned for item in values if (cleaned := strip_markdown_artifacts(item))]


def compact_answer_summary(value: str, *, max_chars: int = 180) -> str:
    """Keep final_answer as a compact summary, leaving details for card fields."""

    text = " ".join(strip_markdown_artifacts(value).split())
    if len(text) <= max_chars:
        return text
    sentence_end = max(text.rfind("。", 0, max_chars), text.rfind(".", 0, max_chars))
    if sentence_end >= 40:
        return text[: sentence_end + 1]
    return f"{text[: max_chars - 1]}…"
