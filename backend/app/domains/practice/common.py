from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.shared.schemas.contracts import PracticeRecommendation

OPTION_KEYS = ("A", "B", "C", "D")
MAX_RECENT_TOPICS = 10


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_user_style_instruction(style_name: str, style_prompt: str) -> str:
    _ = (style_name, style_prompt)
    return "用户自定义风格已暂时禁用；保持专业、清晰、教学友好。"


def normalize_options(options: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for option in list(options or []):
        key = str(option.get("key", "") or "").strip().upper()
        text = str(option.get("text", "") or "").strip()
        if key in OPTION_KEYS and text:
            normalized.append({"key": key, "text": text})
    return normalized[:4]


def normalize_option_rationales(raw: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in OPTION_KEYS:
        value = str((raw or {}).get(key, "") or "").strip()
        if value:
            normalized[key] = value
    return normalized


def normalize_practice_source_type(raw: Any, *, fallback: str = "ai_generated") -> str:
    """Keep practice source_type compatible with the legacy attempts table."""

    value = str(raw or fallback or "ai_generated").strip()
    if value == "question_bank":
        return "question_bank"
    return "ai_generated"


def normalize_quiz_item(raw: dict[str, Any], *, fallback_source_type: str = "ai_generated") -> PracticeRecommendation:
    source_name = str(raw.get("source_name", "") or "").strip()
    source_year = raw.get("source_year")
    return PracticeRecommendation(
        question_id=str(raw.get("question_id") or raw.get("id") or uuid.uuid4()),
        question=str(raw.get("question", "") or "").strip(),
        options=normalize_options(raw.get("options")),
        correct_option=str(raw.get("correct_option", "") or "").strip().upper()[:1] or "A",
        explanation=str(raw.get("explanation", "") or "").strip(),
        option_rationales=normalize_option_rationales(raw.get("option_rationales")),
        knowledge_point=str(raw.get("knowledge_point", "") or "").strip(),
        difficulty=str(raw.get("difficulty", "基础") or "基础").strip(),
        source_type=normalize_practice_source_type(raw.get("source_type", fallback_source_type)),
        source_name=source_name,
        source_year=int(source_year) if isinstance(source_year, int) else None,
        hint=str(raw.get("hint", "") or "").strip(),
    )


def determine_difficulty(topic: str, error_count: dict[str, int]) -> Literal["基础", "变式", "易错"]:
    errors = error_count.get(topic, 0)
    if errors <= 1:
        return "基础"
    if errors <= 3:
        return "变式"
    return "易错"


def infer_topic_from_question(question: str, subject_name: str) -> str:
    english_terms = re.findall(r"[A-Za-z][A-Za-z0-9+/#._-]*", question)
    if english_terms:
        return english_terms[0]

    patterns = [
        r"关于(.+?)(?:的)?(?:练习题|题目|题|知识点)",
        r"(.+?)(?:的)?(?:练习题|题目|题)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            candidate = match.group(1).strip(" ，。！？、")
            if candidate:
                return candidate[:30]

    cleaned = re.sub(
        r"(给我|请|帮我|来|出|几道|两道|一道|一些|再来|练习题|题目|做题|我要|关于|帮忙|生成|选择题)",
        " ",
        question,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。！？、")
    if cleaned:
        return cleaned[:30]

    return subject_name or "综合"


def parse_mcq_text(question: str) -> tuple[str, list[dict[str, str]]]:
    matches = list(
        re.finditer(
            r"(?im)^\s*([A-D])[\.\．、:：\)]\s*(.+?)\s*$",
            question or "",
        )
    )
    options: list[dict[str, str]] = []
    for match in matches:
        key = match.group(1).upper()
        text = match.group(2).strip()
        if key in OPTION_KEYS and text:
            options.append({"key": key, "text": text})

    stem_end = matches[0].start() if matches else len(question or "")
    stem = (question or "")[:stem_end].strip()
    stem = re.sub(r"\s+", " ", stem)
    return stem or "选择题", options[:4]


def extract_mcq_answer_letter(text: str) -> str | None:
    patterns = [
        r"正确答案是\s*([A-D])",
        r"答案是\s*([A-D])",
        r"正确选项[为是：:\s]*([A-D])",
        r"\b([A-D])\b",
    ]
    normalized = (text or "").upper()
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def dedupe_quiz_items(items: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        payload = item.model_dump() if isinstance(item, BaseModel) else dict(item)
        key = payload.get("question_id") or payload.get("question")
        if key in seen:
            continue
        seen.add(str(key))
        deduped.append(payload)
    return deduped
