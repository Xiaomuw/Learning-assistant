from __future__ import annotations

import re
from typing import Any


_NOTEBOOK_REFERENCE_RE = re.compile(
    r"(notebook|笔记|笔记本|资料|文档|知识库|我的|上传|PDF|pdf|url|URL)",
    re.IGNORECASE,
)

_NOTEBOOK_NOTICE_RE = re.compile(
    r"(?:当前|你的|您(?:的)?|我(?:在)?)(?:\s*)"
    r"(?:notebook|笔记本|笔记|知识库|资料|文档)"
    r"[^。！？!?\n]{0,80}?"
    r"(?:未命中|没有命中|没命中|未找到|没有找到|找不到|暂无|不足|不够)"
    r"[^。！？!?\n]{0,80}?[。！？!?]\s*",
    re.IGNORECASE,
)

_GENERIC_KNOWLEDGE_NOTICE_RE = re.compile(
    r"(?:下面|我)?(?:先)?(?:按|基于)?(?:通用知识|一般知识|基础知识)(?:解释|说明|回答)[：:。！？!?]?\s*",
    re.IGNORECASE,
)


def should_preserve_notebook_notice(final_state: dict[str, Any] | None = None) -> bool:
    """Only show notebook-miss wording when the user explicitly asked for their material."""

    state = final_state or {}
    source_policy = str(state.get("source_policy") or "").strip().lower()
    if source_policy == "notebook_only":
        return True

    question = " ".join(
        str(state.get(key) or "")
        for key in ("question", "user_message", "contextual_question", "resolved_question")
    )
    if not question.strip():
        return False
    material_terms = ("notebook", "笔记", "笔记本", "资料", "文档", "知识库", "上传", "pdf", "url")
    explicit_reference_terms = ("根据", "基于", "按照", "引用", "我的", "这份", "这些", "上传")
    lowered = question.lower()
    return any(term in lowered for term in material_terms) and any(term in question for term in explicit_reference_terms)


def clean_display_answer(text: str, *, preserve_notebook_notice: bool = False) -> str:
    """Clean user-facing answer text without changing backend observability payloads."""

    normalized = str(text or "").strip()
    if not normalized:
        return ""

    if not preserve_notebook_notice:
        normalized = _NOTEBOOK_NOTICE_RE.sub("", normalized)
        normalized = _GENERIC_KNOWLEDGE_NOTICE_RE.sub("", normalized)

    normalized = _collapse_adjacent_duplicate_paragraphs(normalized)
    normalized = _collapse_adjacent_duplicate_sentences(normalized)
    normalized = _fix_common_numbered_list_restarts(normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _collapse_adjacent_duplicate_paragraphs(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        return text.strip()

    result: list[str] = []
    previous = ""
    for paragraph in paragraphs:
        key = _dedupe_key(paragraph)
        if key and key == previous:
            continue
        result.append(paragraph)
        previous = key
    return "\n\n".join(result)


def _collapse_adjacent_duplicate_sentences(text: str) -> str:
    parts = re.split(r"(?<=[。！？!?])(\s*)", text)
    if len(parts) <= 1:
        return text

    result: list[str] = []
    previous_key = ""
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        stripped = sentence.strip()
        key = _dedupe_key(stripped)
        if stripped and key and key == previous_key:
            continue
        result.append(sentence + separator)
        if stripped:
            previous_key = key
    return "".join(result)


def _fix_common_numbered_list_restarts(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    expected = 1
    in_numbered_block = False
    for line in lines:
        match = re.match(r"^(\s*)(\d+)([.、])(\s+.*)$", line)
        if not match:
            result.append(line)
            if line.strip() == "":
                in_numbered_block = False
                expected = 1
            continue
        prefix, raw_number, punctuation, rest = match.groups()
        number = int(raw_number)
        if not in_numbered_block:
            in_numbered_block = True
            expected = number
        if number < expected:
            number = expected
        result.append(f"{prefix}{number}{punctuation}{rest}")
        expected = number + 1
    return "\n".join(result)


def _dedupe_key(value: str) -> str:
    normalized = strip_soft_notebook_notice(value)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.strip("：:，,。！？!?；;")
    return normalized


def strip_soft_notebook_notice(value: str) -> str:
    normalized = str(value or "")
    if _NOTEBOOK_REFERENCE_RE.search(normalized):
        normalized = _NOTEBOOK_NOTICE_RE.sub("", normalized)
        normalized = _GENERIC_KNOWLEDGE_NOTICE_RE.sub("", normalized)
    return normalized.strip()
