from __future__ import annotations

from typing import Any

from app.services.rag.rag_service import (
    IngestWriteSummary,
    count_documents,
    delete_knowledge_base,
    diagnose_knowledge_base,
    index_documents,
    index_documents_with_summary,
)
from app.shared.schemas.contracts import NotebookKnowledgeStatus


def count_notebook_documents(subject_id: str) -> int:
    return count_documents(subject_id=subject_id)


def get_notebook_knowledge_status(subject_id: str, user_id: str | None = None) -> NotebookKnowledgeStatus:
    return diagnose_knowledge_base(subject_id=subject_id, user_id=user_id)


def delete_notebook_knowledge_base(subject_id: str) -> None:
    delete_knowledge_base(subject_id=subject_id)


def ingest_notebook_documents(
    *,
    subject_id: str,
    user_id: str | None = None,
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> int:
    return index_documents(texts=texts, metadatas=metadatas, subject_id=subject_id, user_id=user_id)


def ingest_notebook_documents_with_summary(
    *,
    subject_id: str,
    user_id: str | None = None,
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> IngestWriteSummary:
    return index_documents_with_summary(
        texts=texts,
        metadatas=metadatas,
        subject_id=subject_id,
        user_id=user_id,
    )
