from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.shared.schemas.contracts import QuestionBankItemRecord


@dataclass(frozen=True)
class RagSourceDocument:
    """Raw document ready for chunking and vector indexing."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def build_source_document(
    *,
    content: str,
    subject_id: str,
    doc_type: str,
    source: str,
    source_id: str,
    knowledge_point: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> RagSourceDocument:
    metadata = dict(extra_metadata or {})
    metadata.update(
        {
            "subject_id": subject_id,
            "doc_type": doc_type,
            "source": source,
            "source_id": source_id,
            "knowledge_point": knowledge_point,
        }
    )
    return RagSourceDocument(content=str(content or ""), metadata=metadata)


def build_chapter_document(
    *,
    subject_id: str,
    title: str,
    content: str,
    source_id: str,
    source: str = "generated:knowledge_framework",
) -> RagSourceDocument:
    return build_source_document(
        content=f"{title}\n\n{content}",
        subject_id=subject_id,
        doc_type="chapter",
        source=source,
        source_id=source_id,
        knowledge_point=title,
    )


def question_bank_item_to_document(item: QuestionBankItemRecord | dict[str, Any]) -> RagSourceDocument:
    record = QuestionBankItemRecord.model_validate(item)
    exam_scope_tags = [
        tag for tag in record.tags
        if tag in {"408", "考研数学一", "考研数学二", "考研数学三", "大学期末"}
    ]
    options = "\n".join(
        f"{option.get('key', '')}. {option.get('text', '')}"
        for option in record.options
        if option.get("key") and option.get("text")
    )
    rationales = "\n".join(
        f"{key}. {value}"
        for key, value in record.option_rationales.items()
        if value
    )
    content = "\n\n".join(
        part
        for part in [
            f"题目：{record.question}",
            f"选项：\n{options}" if options else "",
            f"正确答案：{record.correct_option}",
            f"标准解析：{record.explanation}",
            f"选项解析：\n{rationales}" if rationales else "",
            f"知识点：{record.knowledge_point}",
            f"难度：{record.difficulty}",
            f"来源：{record.source_name} {record.source_year or ''}".strip(),
        ]
        if part
    )
    return build_source_document(
        content=content,
        subject_id=record.subject_id or "general",
        doc_type="question_bank",
        source=record.source_name or "question_bank",
        source_id=record.question_id or record.id,
        knowledge_point=record.knowledge_point,
        extra_metadata={
            "chapter_id": record.chapter_id,
            "topic_id": record.topic_id,
            "concept_id": record.concept_id,
            "concept_name": record.concept_name,
            "concept_mapping_status": record.concept_mapping_status,
            "difficulty": record.difficulty,
            "source_year": record.source_year,
            "tags": record.tags,
            "exam_scope": exam_scope_tags,
        },
    )


def practice_question_to_document(item: Mapping[str, Any] | object) -> RagSourceDocument:
    question_id = _text(_practice_field(item, "question_id") or _practice_field(item, "id"))
    subject_id = _text(_practice_field(item, "subject_id")) or "general"
    concept_id = _text(_practice_field(item, "concept_id"))
    concept_name = _text(_practice_field(item, "concept_name"))
    difficulty = _text(_practice_field(item, "difficulty"))
    knowledge_points = _string_list(
        _practice_field(
            item,
            "knowledge_points",
            _practice_field(item, "knowledge_points_json", []),
        )
    )
    knowledge_point_text = "、".join(knowledge_points)
    options = _format_practice_options(
        _practice_field(item, "options", _practice_field(item, "options_json", {}))
    )
    stem = _text(_practice_field(item, "stem"))
    answer = _text(_practice_field(item, "answer"))
    explanation = _text(_practice_field(item, "explanation"))
    common_trap = _text(_practice_field(item, "common_trap"))

    content = "\n\n".join(
        part
        for part in [
            f"题干：{stem}" if stem else "",
            f"选项：\n{options}" if options else "",
            f"答案：{answer}" if answer else "",
            f"解析：{explanation}" if explanation else "",
            f"知识点：{knowledge_point_text}" if knowledge_point_text else "",
            f"常见误区：{common_trap}" if common_trap else "",
        ]
        if part
    )
    return build_source_document(
        content=content,
        subject_id=subject_id,
        doc_type="question_bank",
        source="practice_question",
        source_id=question_id,
        knowledge_point=knowledge_point_text or concept_name,
        extra_metadata={
            "source_table": "practice_question",
            "question_id": question_id,
            "concept_id": concept_id,
            "concept_name": concept_name,
            "difficulty": difficulty,
        },
    )


def _practice_field(item: Mapping[str, Any] | object, key: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _format_practice_options(value: Any) -> str:
    if isinstance(value, Mapping):
        option_keys = [key for key in ("A", "B", "C", "D") if key in value]
        option_keys.extend(
            sorted(
                str(key)
                for key in value
                if str(key) not in {"A", "B", "C", "D"}
            )
        )
        return "\n".join(
            f"{key}. {_text(value.get(key))}"
            for key in option_keys
            if _text(value.get(key))
        )
    if isinstance(value, list):
        lines = []
        for option in value:
            if isinstance(option, Mapping):
                key = _text(option.get("key") or option.get("label")).upper()
                text = _text(option.get("text") or option.get("value"))
                if key and text:
                    lines.append(f"{key}. {text}")
            elif _text(option):
                lines.append(_text(option))
        return "\n".join(lines)
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.replace("；", ";").replace("，", ",").replace(";", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value if _text(item)]
    return []


def _text(value: Any) -> str:
    return str(value or "").strip()
