from __future__ import annotations

from typing import Any

from app.services.rag.loader import practice_question_to_document, question_bank_item_to_document
from app.services.rag.rag_service import index_documents
from app.shared.schemas.contracts import QuestionBankItemRecord


def index_notebook_documents(
    *,
    subject_id: str,
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> int:
    return index_documents(texts=texts, metadatas=metadatas, subject_id=subject_id)


def index_question_bank_items(items: list[QuestionBankItemRecord | dict[str, Any]]) -> int:
    documents_by_subject: dict[str, list] = {}
    for raw_item in items:
        item = QuestionBankItemRecord.model_validate(raw_item)
        if not item.question:
            continue
        document = question_bank_item_to_document(item)
        documents_by_subject.setdefault(item.subject_id or "general", []).append(document)

    written = 0
    for subject_id, documents in documents_by_subject.items():
        written += index_documents(subject_id=subject_id, documents=documents)
    return written


def index_practice_questions(items: list[Any]) -> int:
    documents_by_subject: dict[str, list] = {}
    for item in items:
        document = practice_question_to_document(item)
        if not document.content.strip():
            continue
        subject_id = str(document.metadata.get("subject_id") or "general")
        documents_by_subject.setdefault(subject_id, []).append(document)

    written = 0
    for subject_id, documents in documents_by_subject.items():
        written += index_documents(subject_id=subject_id, documents=documents)
    return written
