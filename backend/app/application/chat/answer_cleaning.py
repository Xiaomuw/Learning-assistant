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

_PLANNING_PHRASE_PATTERNS = (
    re.compile(r"(?:用户|你|您)(?:想|希望|需要|正在|是想)(?:了解|知道|询问|学习|掌握)[^。！？!?\n]{0,120}[。！？!?\n]?\s*"),
    re.compile(r"(?:我|我们|下面)(?:会|将|先|来|要|可以)[^。！？!?\n]{0,120}(?:讲解|说明|解释|回答|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*"),
    re.compile(r"(?:需要|可以|应该|最好)?从[^。！？!?\n]{0,100}(?:方面|角度|维度)(?:来)?(?:讲解|说明|解释|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*"),
    re.compile(r"(?:按|按照)[^。！？!?\n]{0,80}(?:结构|顺序)(?:讲解|说明|解释|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*"),
)

_TEACHING_ANSWER_TYPES = {"", "concept", "problem", "compare", "application", "review", "mcq_problem"}
_MIN_TEACHING_ANSWER_CHARS = 36


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

    normalized = _strip_planning_phrases(normalized)

    if not preserve_notebook_notice:
        normalized = _NOTEBOOK_NOTICE_RE.sub("", normalized)
        normalized = _GENERIC_KNOWLEDGE_NOTICE_RE.sub("", normalized)

    normalized = _collapse_adjacent_duplicate_paragraphs(normalized)
    normalized = _collapse_adjacent_duplicate_sentences(normalized)
    normalized = _collapse_seen_duplicate_sentences(normalized)
    normalized = _fix_common_numbered_list_restarts(normalized)
    normalized = _tidy_display_text(normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def compose_display_answer(
    final_answer: str,
    explanation: dict[str, Any] | None = None,
    *,
    question_type: str = "",
    preserve_notebook_notice: bool = False,
) -> str:
    """Build the user-visible answer without leaking planning/thinking text."""

    explanation = explanation if isinstance(explanation, dict) else {}
    final_clean = clean_display_answer(
        final_answer,
        preserve_notebook_notice=preserve_notebook_notice,
    )
    steps = clean_display_steps(
        explanation.get("steps"),
        preserve_notebook_notice=preserve_notebook_notice,
    )
    if _should_use_final_answer(final_clean, steps, question_type=question_type):
        return final_clean

    if steps and _should_use_steps_as_answer(steps, question_type=question_type):
        step_answer = clean_display_answer(
            "\n\n".join(steps),
            preserve_notebook_notice=preserve_notebook_notice,
        )
        if step_answer:
            return step_answer

    if final_clean:
        return final_clean

    topic = clean_display_answer(str(explanation.get("topic") or ""), preserve_notebook_notice=True)
    if topic:
        return f"我已经围绕「{topic}」整理好讲解了。"
    return "这轮暂时没有生成完整答案，请换一种问法再试。"


def clean_display_steps(
    values: Any,
    *,
    preserve_notebook_notice: bool = False,
) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = clean_display_answer(
            str(item or ""),
            preserve_notebook_notice=preserve_notebook_notice,
        )
        if not cleaned:
            continue
        key = _dedupe_key(cleaned)
        if key and key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _collapse_adjacent_duplicate_paragraphs(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        return text.strip()

    result: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        key = _dedupe_key(paragraph)
        if key and key in seen:
            continue
        result.append(paragraph)
        if key:
            seen.add(key)
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


def _collapse_seen_duplicate_sentences(text: str) -> str:
    parts = re.split(r"(?<=[。！？!?])(\s*)", text)
    if len(parts) <= 1:
        return text

    result: list[str] = []
    seen: set[str] = set()
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        stripped = sentence.strip()
        key = _dedupe_key(stripped)
        if stripped and key:
            if key in seen:
                continue
            seen.add(key)
        result.append(sentence + separator)
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


def _should_use_final_answer(
    final_answer: str,
    steps: list[str],
    *,
    question_type: str,
) -> bool:
    if not final_answer:
        return False
    if _looks_like_planning_text(final_answer):
        return False
    normalized_type = str(question_type or "").strip()
    if normalized_type in _TEACHING_ANSWER_TYPES and steps:
        if len(re.sub(r"\s+", "", final_answer)) < _MIN_TEACHING_ANSWER_CHARS:
            return False
    return True


def _should_use_steps_as_answer(
    steps: list[str],
    *,
    question_type: str,
) -> bool:
    if not steps:
        return False
    normalized_type = str(question_type or "").strip()
    return normalized_type in _TEACHING_ANSWER_TYPES


def _looks_like_planning_text(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PLANNING_PHRASE_PATTERNS)


def _strip_planning_phrases(value: str) -> str:
    normalized = str(value or "")
    for pattern in _PLANNING_PHRASE_PATTERNS:
        normalized = pattern.sub("", normalized)
    return _tidy_display_text(normalized)


def _tidy_display_text(value: str) -> str:
    normalized = str(value or "")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = "\n".join(line.strip() for line in normalized.split("\n"))
    normalized = re.sub(r"[，,]\s*([。！？!?])", r"\1", normalized)
    normalized = re.sub(r"[：:]\s*([。！？!?])", r"\1", normalized)
    normalized = normalized.strip()
    if normalized.endswith(("，", ",", "：", ":")):
        normalized = normalized[:-1].rstrip() + "。"
    return normalized


def strip_soft_notebook_notice(value: str) -> str:
    normalized = str(value or "")
    if _NOTEBOOK_REFERENCE_RE.search(normalized):
        normalized = _NOTEBOOK_NOTICE_RE.sub("", normalized)
        normalized = _GENERIC_KNOWLEDGE_NOTICE_RE.sub("", normalized)
    return normalized.strip()
