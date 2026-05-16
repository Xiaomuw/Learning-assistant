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
_MAX_CONCEPT_PARAGRAPH_CHARS = 180
_ANALOGY_LEAD_MARKERS = (
    "想象",
    "例如",
    "比如",
    "举个例子",
    "打个比方",
    "就像",
    "好比",
    "类似",
    "可以把",
    "你可以把",
    "假设",
    "当你",
)
_ANALOGY_SCENE_MARKERS = (
    "餐厅",
    "点餐",
    "厨师",
    "服务员",
    "快递",
    "外卖",
    "包裹",
    "寄件",
    "收件",
    "图书馆",
    "邮局",
)
_SECTION_HEADING_RE = re.compile(
    r"(?P<heading>"
    r"(?:为什么(?:需要|要)\s*[A-Za-z0-9\u4e00-\u9fff/+\-.#]{0,32}|"
    r"[A-Za-z0-9\u4e00-\u9fff/+\-.#]{0,32}\s*(?:是\s*什么|是什么|如何工作|怎么工作|工作方式|"
    r"主要作用|作用|特点|易错点))"
    r"\s*[：:]"
    r")"
)
_DEFINITION_SENTENCE_RE = re.compile(
    r"(?P<sentence>"
    r"(?:[A-Za-z][A-Za-z0-9/+\-.#]{1,32}|[\u4e00-\u9fff]{2,12})"
    r"(?:\s*[（(][^）)]{1,80}[）)])?"
    r"\s*(?:全称是|是一种|是一个|是一套|是|指|属于|就是)"
    r"[^。！？!?\n]{8,220}[。！？!?]?"
    r")"
)
_PREFERRED_DEFINITION_TERMS = (
    "http",
    "https",
    "tcp",
    "udp",
    "ip",
    "dns",
    "递归",
    "进程",
    "线程",
    "缓存",
    "队列",
    "栈",
    "链表",
    "二叉树",
    "虚拟内存",
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
        return _postprocess_display_answer(final_clean, question_type=question_type)

    if steps and _should_use_steps_as_answer(steps, question_type=question_type):
        step_answer = clean_display_answer(
            "\n\n".join(steps),
            preserve_notebook_notice=preserve_notebook_notice,
        )
        if step_answer:
            return _postprocess_display_answer(step_answer, question_type=question_type)

    if final_clean:
        return _postprocess_display_answer(final_clean, question_type=question_type)

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
        if normalized_type == "concept" and _has_weak_concept_display_shape(final_answer):
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


def _postprocess_display_answer(value: str, *, question_type: str) -> str:
    normalized_type = str(question_type or "").strip()
    if normalized_type == "concept":
        return _prioritize_definition_section(value)
    return value


def _prioritize_definition_section(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    if _starts_with_why_needed(text):
        text = _move_definition_heading_first(text)
    if _starts_with_analogy(text):
        text = _move_definition_sentence_first(text)
    return text


def _move_definition_heading_first(text: str) -> str:
    matches = list(_SECTION_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return text

    segments: list[tuple[str, str]] = []
    prefix = text[: matches[0].start()].strip()
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        if segment:
            segments.append((match.group("heading"), segment))

    definition_index = next(
        (
            index
            for index, (heading, _segment) in enumerate(segments)
            if "是什么" in re.sub(r"\s+", "", heading) or "是什么" in heading
        ),
        -1,
    )
    if definition_index <= 0:
        return text

    ordered = [segments[definition_index], *segments[:definition_index], *segments[definition_index + 1 :]]
    paragraphs = [segment for _heading, segment in ordered]
    if prefix:
        paragraphs.append(prefix)
    return "\n\n".join(_tidy_display_text(paragraph) for paragraph in paragraphs if paragraph.strip()).strip()


def _move_definition_sentence_first(text: str) -> str:
    matches = list(_DEFINITION_SENTENCE_RE.finditer(text))
    if not matches:
        return text

    selected = max(matches, key=_definition_sentence_score)
    if selected.start() <= 0:
        return text
    if _definition_sentence_score(selected) <= 0:
        return text

    definition = _tidy_display_text(selected.group("sentence"))
    before = text[: selected.start()].strip()
    after = text[selected.end() :].strip()
    remainder = " ".join(part for part in (before, after) if part)
    remainder = _tidy_display_text(remainder)
    if not definition or not remainder:
        return text
    return f"{definition}\n\n{remainder}".strip()


def _definition_sentence_score(match: re.Match[str]) -> int:
    sentence = str(match.group("sentence") or "")
    prefix = re.split(r"\s*(?:全称是|是一种|是一个|是一套|是|指|属于|就是)", sentence, maxsplit=1)[0]
    lowered_sentence = sentence.lower()
    lowered_prefix = prefix.lower()
    score = 0
    if any(term in lowered_sentence for term in _PREFERRED_DEFINITION_TERMS):
        score += 6
    if re.search(r"\b[A-Z][A-Za-z0-9/+\-.#]{1,}\b", prefix):
        score += 4
    if any(marker in sentence for marker in _ANALOGY_SCENE_MARKERS):
        score -= 3
    if len(re.sub(r"\s+", "", prefix)) > 18:
        score -= 2
    if any(term in lowered_prefix for term in ("厨房", "服务员", "顾客", "浏览器", "服务器")) and not any(
        term in lowered_prefix for term in _PREFERRED_DEFINITION_TERMS
    ):
        score -= 4
    return score


def _starts_with_why_needed(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").strip())[:80]
    return compact.startswith("为什么需要") or compact.startswith("为什么要")


def _has_weak_concept_display_shape(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if _starts_with_analogy(text):
        return True
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if len(paragraphs) <= 1 and len(re.sub(r"\s+", "", text)) > _MAX_CONCEPT_PARAGRAPH_CHARS:
        return True
    return any(len(re.sub(r"\s+", "", paragraph)) > _MAX_CONCEPT_PARAGRAPH_CHARS for paragraph in paragraphs)


def _starts_with_analogy(value: str) -> bool:
    first_sentence = re.split(r"[。！？!?]", str(value or "").strip(), maxsplit=1)[0][:140]
    if not first_sentence:
        return False
    has_lead = any(marker in first_sentence for marker in _ANALOGY_LEAD_MARKERS)
    has_scene = any(marker in first_sentence for marker in _ANALOGY_SCENE_MARKERS)
    return has_lead or has_scene


def _strip_planning_phrases(value: str) -> str:
    normalized = str(value or "")
    for pattern in _PLANNING_PHRASE_PATTERNS:
        normalized = pattern.sub("", normalized)
    return _tidy_display_text(normalized)


def _tidy_display_text(value: str) -> str:
    normalized = str(value or "")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = "\n".join(line.strip() for line in normalized.split("\n"))
    normalized = re.sub(r"(?<=[。！？!?])[ \t]+(?=[\u4e00-\u9fffA-Za-z0-9])", "", normalized)
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
