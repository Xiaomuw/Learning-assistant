from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.rag.loader import RagSourceDocument
from app.services.rag.retriever import (
    DEFAULT_RELEVANCE_THRESHOLD,
    diagnose_retrieval,
    filter_relevant_documents,
    get_retrieval_contextual_query,
    retrieve,
)
from app.services.rag.vector_store import (
    count_collection_documents,
    delete_collection,
    get_collection_document_status,
    upsert_documents,
)
from app.shared.schemas.contracts import NotebookKnowledgeStatus, RetrievalDiagnostics, RetrievedDocument


@dataclass(frozen=True)
class RagContextResult:
    raw_docs: list[RetrievedDocument] = field(default_factory=list)
    docs: list[RetrievedDocument] = field(default_factory=list)
    diagnosis: RetrievalDiagnostics = field(default_factory=RetrievalDiagnostics)
    contextual_query: str = ""
    is_rewritten: bool = False
    rag_ready: bool = False
    warning: str = ""
    relevance: dict[str, Any] = field(default_factory=dict)


def index_documents(
    *,
    subject_id: str,
    user_id: str | None = None,
    documents: list[RagSourceDocument] | None = None,
    texts: list[str] | None = None,
    metadatas: list[dict[str, Any]] | None = None,
) -> int:
    if documents is not None:
        texts = [document.content for document in documents]
        metadatas = [document.metadata for document in documents]
    return upsert_documents(
        texts=list(texts or []),
        metadatas=metadatas,
        subject_id=subject_id,
        user_id=user_id,
    )


def retrieve_context(
    *,
    question: str,
    subject_id: str | None,
    user_id: str | None = None,
    memory: dict[str, Any] | None = None,
    short_term_messages: list[dict[str, Any]] | None = None,
    session_memory: dict[str, Any] | None = None,
    top_k: int = 5,
    min_score: float = DEFAULT_RELEVANCE_THRESHOLD,
    doc_types: list[str] | None = None,
) -> RagContextResult:
    contextual_query = get_retrieval_contextual_query(
        question,
        short_term_messages or [],
        session_memory or {},
        memory or {},
    )
    raw_docs = retrieve(
        query=contextual_query,
        top_k=top_k,
        subject_id=subject_id,
        user_id=user_id,
        doc_types=doc_types,
    )
    filtered_docs, relevance = filter_relevant_documents(
        query=contextual_query,
        docs=raw_docs,
        threshold=min_score,
    )
    diagnosis = diagnose_retrieval(
        query=contextual_query,
        docs=filtered_docs,
        subject_id=subject_id,
        user_id=user_id,
        min_ready_score=min_score,
    )
    return RagContextResult(
        raw_docs=raw_docs,
        docs=filtered_docs,
        diagnosis=diagnosis,
        contextual_query=contextual_query,
        is_rewritten=contextual_query != question,
        rag_ready=diagnosis.diagnosis == "ready",
        relevance=relevance,
    )


def diagnose_knowledge_base(subject_id: str | None = None, user_id: str | None = None) -> NotebookKnowledgeStatus:
    return get_collection_document_status(subject_id=subject_id, user_id=user_id)


def count_documents(subject_id: str) -> int:
    return count_collection_documents(subject_id=subject_id)


def delete_knowledge_base(subject_id: str) -> None:
    delete_collection(subject_id=subject_id)
