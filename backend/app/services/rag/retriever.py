from __future__ import annotations

import re

from app.services.rag.query_policy import build_contextual_query
from app.services.rag.vector_store import (
    count_collection_documents,
    delete_collection,
    ensure_collection_ready,
    ensure_vector_store_ready,
    get_collection_document_status,
    get_collection,
    get_collection_by_name,
    ingest_documents,
    search_documents,
    upsert_documents,
    upsert_embedding_rows,
)
from app.shared.schemas.contracts import RetrievalDiagnostics, RetrievedDocument


DEFAULT_RETRIEVAL_DOC_TYPES = ["chapter", "exam_pattern", "pdf", "url", "question_bank", "document"]
DEFAULT_RELEVANCE_THRESHOLD = 0.65

_ENGLISH_STOP_TERMS = {
    "what",
    "is",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "for",
    "and",
    "or",
    "with",
    "about",
    "explain",
    "define",
    "please",
}

_CHINESE_STOP_PHRASES = (
    "什么是",
    "什么叫",
    "解释一下",
    "解释下",
    "介绍一下",
    "介绍下",
    "根据",
    "依据",
    "基于",
    "当前",
    "这个",
    "我的",
    "notebook",
    "笔记本",
    "资料",
    "文档",
    "讲一下",
    "能给我",
    "帮我",
)


def retrieve(
    query: str,
    top_k: int = 5,
    subject_id: str | None = None,
    doc_types: list[str] | None = None,
    min_score: float | None = None,
    user_id: str | None = None,
) -> list[RetrievedDocument]:
    effective_doc_types = doc_types if doc_types is not None else DEFAULT_RETRIEVAL_DOC_TYPES
    return [
        RetrievedDocument.model_validate(item)
        for item in search_documents(
            query=query,
            top_k=top_k,
            subject_id=subject_id,
            doc_types=effective_doc_types,
            min_score=min_score,
            user_id=user_id,
        )
    ]


def diagnose_retrieval(
    *,
    query: str,
    docs: list[RetrievedDocument],
    subject_id: str | None = None,
    user_id: str | None = None,
    min_ready_score: float = 0.5,
) -> RetrievalDiagnostics:
    status = get_collection_document_status(subject_id=subject_id, user_id=user_id)
    doc_type_counts: dict[str, int] = {}
    for doc in docs:
        doc_type = str(doc.metadata.get("doc_type") or "unknown")
        doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1

    top_score = max((doc.score for doc in docs), default=0.0)
    if status.doc_count <= 0:
        diagnosis = "empty_knowledge_base"
    elif not docs:
        diagnosis = "no_matching_docs"
    elif top_score < min_ready_score:
        diagnosis = "low_score"
    else:
        diagnosis = "ready"

    return RetrievalDiagnostics(
        query=query,
        hit_count=len(docs),
        top_score=round(float(top_score), 4),
        doc_type_counts=doc_type_counts,
        diagnosis=diagnosis,
        coverage_level=status.coverage_level,
        suggested_actions=status.suggested_actions,
    )


def score_and_filter(
    docs: list[RetrievedDocument],
    threshold: float = 0.65,
) -> list[RetrievedDocument]:
    if not docs:
        return []
    filtered = [doc for doc in docs if doc.score >= threshold]
    filtered.sort(key=lambda item: item.score, reverse=True)
    return filtered


def extract_query_key_terms(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (query or "")).strip()
    if not normalized:
        return []

    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", normalized):
        lowered = token.lower().strip(".-")
        if lowered and lowered not in _ENGLISH_STOP_TERMS:
            terms.append(lowered)

    chinese_text = normalized
    for phrase in _CHINESE_STOP_PHRASES:
        chinese_text = chinese_text.replace(phrase, " ")
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", chinese_text):
        if len(chunk) <= 10:
            terms.append(chunk)
        else:
            # 粗粒度中文问题没有分词器时，用相邻二字片段补充主题匹配信号。
            terms.extend(chunk[index : index + 2] for index in range(0, len(chunk) - 1))

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized_term = term.lower().strip()
        if normalized_term and normalized_term not in seen:
            seen.add(normalized_term)
            deduped.append(normalized_term)
    return deduped[:8]


def _document_search_text(doc: RetrievedDocument) -> str:
    metadata_values = " ".join(str(value) for value in (doc.metadata or {}).values() if value)
    return f"{doc.content}\n{metadata_values}".lower()


def _has_key_term_overlap(doc: RetrievedDocument, key_terms: list[str]) -> bool:
    if not key_terms:
        return True
    haystack = _document_search_text(doc)
    return any(term.lower() in haystack for term in key_terms)


def filter_relevant_documents(
    *,
    query: str,
    docs: list[RetrievedDocument],
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
) -> tuple[list[RetrievedDocument], dict[str, object]]:
    """Filter retrieved context by both score and query topic overlap."""
    raw_docs = list(docs or [])
    key_terms = extract_query_key_terms(query)
    score_filtered = score_and_filter(raw_docs, threshold=threshold)

    filtered: list[RetrievedDocument] = []
    discarded_for_terms = 0
    for doc in score_filtered:
        if _has_key_term_overlap(doc, key_terms):
            filtered.append(doc)
        else:
            discarded_for_terms += 1

    filtered.sort(key=lambda item: item.score, reverse=True)
    top_score = max((doc.score for doc in raw_docs), default=0.0)
    if not raw_docs:
        reason = "no_raw_docs"
    elif not score_filtered:
        reason = "all_below_score_threshold"
    elif not filtered:
        reason = "no_core_term_overlap"
    else:
        reason = "ready"

    return filtered, {
        "query": query,
        "threshold": threshold,
        "raw_count": len(raw_docs),
        "score_kept_count": len(score_filtered),
        "kept_count": len(filtered),
        "discarded_count": len(raw_docs) - len(filtered),
        "discarded_for_terms": discarded_for_terms,
        "top_score": round(float(top_score), 4),
        "key_terms": key_terms,
        "reason": reason,
    }


def get_retrieval_contextual_query(
    question: str,
    short_term_messages: list[dict[str, object]],
    session_memory: dict[str, object] | None,
    memory: dict[str, object],
) -> str:
    return build_contextual_query(question, short_term_messages, session_memory, memory)
