from __future__ import annotations

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
            "difficulty": record.difficulty,
            "source_year": record.source_year,
            "tags": record.tags,
            "exam_scope": exam_scope_tags,
        },
    )
