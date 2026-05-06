from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from langchain_core.documents import Document
from langchain_postgres import PGVector
from loguru import logger
from sqlalchemy import inspect, text

from app.infrastructure.db.database import engine, get_sqlalchemy_database_url
from app.services.rag.embeddings import get_embedding_function
from app.services.rag.splitter import build_text_splitter
from app.shared.schemas.contracts import NotebookKnowledgeStatus

_store_cache: dict[str, PGVector] = {}
_embedding_table_columns_cache: set[str] | None = None

PGVECTOR_COLLECTION_TABLE = "langchain_pg_collection"
PGVECTOR_EMBEDDING_TABLE = "langchain_pg_embedding"


def get_default_collection_name() -> str:
    return os.getenv("PGVECTOR_DEFAULT_COLLECTION", "learning_docs")


def get_collection_prefix() -> str:
    return os.getenv("PGVECTOR_COLLECTION_PREFIX", "learning")


def resolve_collection_name(subject_id: str | None = None) -> str:
    if subject_id:
        return f"{get_collection_prefix()}_{subject_id}"
    return get_default_collection_name()


def _safe_collection_part(value: str | None, default: str = "general") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip())
    return normalized.strip("_") or default


def resolve_personal_collection_name(subject_id: str | None, user_id: str | None) -> str:
    return (
        f"{get_collection_prefix()}_user_"
        f"{_safe_collection_part(user_id, 'anonymous')}_{_safe_collection_part(subject_id)}"
    )


def resolve_effective_collection_name(subject_id: str | None = None, user_id: str | None = None) -> str:
    if user_id:
        return resolve_personal_collection_name(subject_id, user_id)
    return resolve_collection_name(subject_id)


def get_collection_by_name(collection_name: str) -> PGVector:
    store = _store_cache.get(collection_name)
    if store is None:
        store = PGVector(
            embeddings=get_embedding_function(),
            collection_name=collection_name,
            connection=get_sqlalchemy_database_url(),
        )
        _store_cache[collection_name] = store
        logger.info(f"✅ PGVector collection '{collection_name}' 已就绪")
    return store


def get_collection(subject_id: str | None = None, user_id: str | None = None) -> PGVector:
    return get_collection_by_name(resolve_effective_collection_name(subject_id, user_id))


def ensure_vector_store_ready(subject_id: str | None = None, user_id: str | None = None) -> PGVector:
    return get_collection(subject_id=subject_id, user_id=user_id)


def ensure_collection_ready(collection_name: str) -> PGVector:
    return get_collection_by_name(collection_name)


def pgvector_tables_ready() -> bool:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    return {PGVECTOR_COLLECTION_TABLE, PGVECTOR_EMBEDDING_TABLE}.issubset(table_names)


def _embedding_table_columns() -> set[str]:
    global _embedding_table_columns_cache
    if _embedding_table_columns_cache is None:
        inspector = inspect(engine)
        _embedding_table_columns_cache = {
            str(column["name"])
            for column in inspector.get_columns(PGVECTOR_EMBEDDING_TABLE)
        }
    return _embedding_table_columns_cache


def count_collection_documents(subject_id: str | None = None, user_id: str | None = None) -> int:
    if not pgvector_tables_ready():
        return 0
    collection_name = resolve_effective_collection_name(subject_id, user_id)
    stmt = text(
        f"""
        SELECT COUNT(*)
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        """
    )
    with engine.begin() as connection:
        count = connection.execute(stmt, {"collection_name": collection_name}).scalar_one()
    return int(count or 0)


def _build_coverage_fields(
    *,
    doc_count: int,
    chapter_count: int,
    exam_pattern_count: int,
    question_count: int,
    url_count: int,
    pdf_count: int,
    embedding_ready: bool,
) -> dict[str, Any]:
    """Derive a lightweight knowledge-base completeness signal from indexed content."""
    missing_doc_types: list[str] = []
    suggested_actions: list[str] = []

    if chapter_count <= 0:
        missing_doc_types.append("chapter")
        suggested_actions.append("生成知识框架，先补齐章节骨架")

    if exam_pattern_count <= 0:
        missing_doc_types.append("exam_pattern")
        suggested_actions.append("补充常考题型说明，让复习和出题更贴近考试")

    if pdf_count <= 0 and url_count <= 0:
        missing_doc_types.extend(["pdf", "url"])
        suggested_actions.append("上传 PDF 或添加 URL，让 notebook 有真实资料来源")

    if question_count <= 0:
        missing_doc_types.append("question_bank")
        suggested_actions.append("导入题库，补充可练习和可讲解的真题解析")

    if doc_count <= 0:
        return {
            "coverage_score": 0,
            "coverage_level": "empty",
            "missing_doc_types": missing_doc_types,
            "suggested_actions": suggested_actions[:3],
            "retrieval_ready": False,
        }

    coverage_score = 0
    if chapter_count > 0:
        coverage_score += 30
    if exam_pattern_count > 0:
        coverage_score += 20
    if pdf_count > 0:
        coverage_score += 15
    if url_count > 0:
        coverage_score += 15
    if question_count > 0:
        coverage_score += 15
    coverage_score += min(5, max(0, doc_count // 8))
    coverage_score = min(100, coverage_score)

    if coverage_score < 40:
        coverage_level = "sparse"
    elif coverage_score < 75:
        coverage_level = "partial"
    else:
        coverage_level = "ready"

    return {
        "coverage_score": coverage_score,
        "coverage_level": coverage_level,
        "missing_doc_types": missing_doc_types,
        "suggested_actions": suggested_actions[:3],
        "retrieval_ready": bool(embedding_ready and doc_count > 0),
    }


def _empty_counts() -> dict[str, int]:
    return {
        "doc_count": 0,
        "chapter_count": 0,
        "exam_pattern_count": 0,
        "question_count": 0,
        "url_count": 0,
        "pdf_count": 0,
    }


def _get_collection_counts(collection_name: str) -> dict[str, int]:
    if not pgvector_tables_ready():
        return _empty_counts()
    stmt = text(
        f"""
        SELECT
          COUNT(*) AS doc_count,
          COUNT(*) FILTER (WHERE embeddings.cmetadata->>'doc_type' = 'chapter') AS chapter_count,
          COUNT(*) FILTER (WHERE embeddings.cmetadata->>'doc_type' = 'exam_pattern') AS exam_pattern_count,
          COUNT(*) FILTER (WHERE embeddings.cmetadata->>'doc_type' = 'question_bank') AS question_count,
          COUNT(*) FILTER (WHERE embeddings.cmetadata->>'doc_type' = 'url') AS url_count,
          COUNT(*) FILTER (WHERE embeddings.cmetadata->>'doc_type' = 'pdf') AS pdf_count
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        """
    )
    with engine.begin() as connection:
        row = connection.execute(stmt, {"collection_name": collection_name}).mappings().one()
    return {
        "doc_count": int(row["doc_count"] or 0),
        "chapter_count": int(row["chapter_count"] or 0),
        "exam_pattern_count": int(row["exam_pattern_count"] or 0),
        "question_count": int(row["question_count"] or 0),
        "url_count": int(row["url_count"] or 0),
        "pdf_count": int(row["pdf_count"] or 0),
    }


def _sum_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: int(left.get(key, 0)) + int(right.get(key, 0)) for key in _empty_counts()}


def get_collection_document_status(subject_id: str | None = None, user_id: str | None = None) -> NotebookKnowledgeStatus:
    collection_name = resolve_collection_name(subject_id)
    embedding_ready = pgvector_tables_ready()
    shared_counts = _get_collection_counts(collection_name) if embedding_ready else _empty_counts()
    personal_collection_name = resolve_personal_collection_name(subject_id, user_id) if user_id else ""
    personal_counts = (
        _get_collection_counts(personal_collection_name)
        if embedding_ready and user_id
        else _empty_counts()
    )
    total_counts = _sum_counts(shared_counts, personal_counts)
    coverage_fields = _build_coverage_fields(
        doc_count=total_counts["doc_count"],
        chapter_count=total_counts["chapter_count"],
        exam_pattern_count=total_counts["exam_pattern_count"],
        question_count=total_counts["question_count"],
        url_count=total_counts["url_count"],
        pdf_count=total_counts["pdf_count"],
        embedding_ready=embedding_ready,
    )
    return NotebookKnowledgeStatus(
        subject_id=subject_id or "general",
        collection_name=collection_name,
        doc_count=total_counts["doc_count"],
        shared_doc_count=shared_counts["doc_count"],
        personal_doc_count=personal_counts["doc_count"],
        chapter_count=total_counts["chapter_count"],
        exam_pattern_count=total_counts["exam_pattern_count"],
        question_count=total_counts["question_count"],
        url_count=total_counts["url_count"],
        pdf_count=total_counts["pdf_count"],
        personal_pdf_count=personal_counts["pdf_count"],
        personal_url_count=personal_counts["url_count"],
        personal_ready=bool(embedding_ready and personal_counts["doc_count"] > 0),
        embedding_ready=embedding_ready,
        **coverage_fields,
    )


def delete_collection(subject_id: str | None = None) -> None:
    if not pgvector_tables_ready():
        return
    collection_name = resolve_collection_name(subject_id)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                DELETE FROM {PGVECTOR_EMBEDDING_TABLE}
                WHERE collection_id IN (
                    SELECT uuid
                    FROM {PGVECTOR_COLLECTION_TABLE}
                    WHERE name = :collection_name
                )
                """
            ),
            {"collection_name": collection_name},
        )
        connection.execute(
            text(f"DELETE FROM {PGVECTOR_COLLECTION_TABLE} WHERE name = :collection_name"),
            {"collection_name": collection_name},
        )
    _store_cache.pop(collection_name, None)


def delete_source_documents(
    *,
    subject_id: str | None,
    source_id: str,
    doc_type: str | None = None,
    user_id: str | None = None,
) -> int:
    if not pgvector_tables_ready():
        return 0
    collection_name = resolve_effective_collection_name(subject_id, user_id)
    type_clause = "AND embeddings.cmetadata->>'doc_type' = :doc_type" if doc_type else ""
    stmt = text(
        f"""
        DELETE FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        USING {PGVECTOR_COLLECTION_TABLE} AS collections
        WHERE embeddings.collection_id = collections.uuid
          AND collections.name = :collection_name
          AND embeddings.cmetadata->>'source_id' = :source_id
          {type_clause}
        """
    )
    params = {
        "collection_name": collection_name,
        "source_id": source_id,
    }
    if doc_type:
        params["doc_type"] = doc_type
    with engine.begin() as connection:
        result = connection.execute(stmt, params)
    return int(result.rowcount or 0)


def upsert_embedding_rows(collection_name: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    ensure_collection_ready(collection_name)
    has_custom_id_column = "custom_id" in _embedding_table_columns()
    with engine.begin() as connection:
        collection_id = connection.execute(
            text(
                f"""
                SELECT uuid
                FROM {PGVECTOR_COLLECTION_TABLE}
                WHERE name = :collection_name
                """
            ),
            {"collection_name": collection_name},
        ).scalar_one()
        written = 0
        for row in rows:
            custom_id = str(row.get("custom_id") or row.get("id") or uuid.uuid4())
            embedding = list(row.get("embedding") or [])
            document = str(row.get("document", "") or "")
            metadata = dict(row.get("metadata") or {})
            metadata.setdefault("vector_id", custom_id)
            embedding_literal = "[" + ",".join(str(float(value)) for value in embedding) + "]"
            if has_custom_id_column:
                connection.execute(
                    text(
                        f"""
                        DELETE FROM {PGVECTOR_EMBEDDING_TABLE}
                        WHERE collection_id = :collection_id
                          AND custom_id = :custom_id
                        """
                    ),
                    {"collection_id": collection_id, "custom_id": custom_id},
                )
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {PGVECTOR_EMBEDDING_TABLE}
                            (id, collection_id, embedding, document, cmetadata, custom_id)
                        VALUES
                            (:id, :collection_id, CAST(:embedding AS vector), :document, CAST(:metadata AS JSONB), :custom_id)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "collection_id": collection_id,
                        "embedding": embedding_literal,
                        "document": document,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                        "custom_id": custom_id,
                    },
                )
            else:
                connection.execute(
                    text(
                        f"""
                        DELETE FROM {PGVECTOR_EMBEDDING_TABLE}
                        WHERE collection_id = :collection_id
                          AND cmetadata->>'vector_id' = :custom_id
                        """
                    ),
                    {"collection_id": collection_id, "custom_id": custom_id},
                )
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {PGVECTOR_EMBEDDING_TABLE}
                            (id, collection_id, embedding, document, cmetadata)
                        VALUES
                            (:id, :collection_id, CAST(:embedding AS vector), :document, CAST(:metadata AS JSONB))
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "collection_id": collection_id,
                        "embedding": embedding_literal,
                        "document": document,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
            written += 1
    return written


def _score_from_distance(distance: float) -> float:
    return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)


def _normalize_metadata(
    metadata: dict[str, Any],
    *,
    subject_id: str | None,
    text_index: int,
    chunk_index: int,
    vector_id: str,
    user_id: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    target_subject_id = str(subject_id or "general")
    raw_subject_id = str(normalized.get("subject_id") or normalized.get("subject") or "").strip()
    if raw_subject_id and raw_subject_id != target_subject_id:
        logger.warning(
            "⚠️ 向量 metadata subject_id 与目标 collection 不一致，已按目标 notebook 覆盖: "
            f"metadata={raw_subject_id}, target={target_subject_id}"
        )
    source = str(normalized.get("source") or normalized.get("source_name") or "manual")
    source_id = str(normalized.get("source_id") or source or vector_id)
    doc_type = str(normalized.get("doc_type") or "document")
    knowledge_point = str(
        normalized.get("knowledge_point")
        or normalized.get("chapter")
        or normalized.get("topic")
        or ""
    )
    normalized.update(
        {
            "subject_id": target_subject_id,
            "doc_type": doc_type,
            "source": source,
            "source_id": source_id,
            "knowledge_point": knowledge_point,
            "chunk_index": chunk_index,
            "text_index": text_index,
            "vector_id": vector_id,
            "visibility": visibility or ("personal" if user_id else "shared"),
        }
    )
    if user_id:
        normalized["user_id"] = str(user_id)
    return normalized


def _build_vector_id(doc_type: str, source_id: str, text_count: int, text_index: int, chunk_index: int) -> str:
    if doc_type == "question_bank" and text_count == 1:
        return f"question_bank:{source_id}:{chunk_index}"
    return f"{doc_type}:{source_id}:{text_index}:{chunk_index}"


def _write_documents_to_collection(
    *,
    subject_id: str | None,
    user_id: str | None,
    documents: list[Document],
    ids: list[str],
) -> int:
    """Write chunks through the explicit upsert path so metadata and collection cannot drift."""
    if not documents:
        return 0
    collection_name = resolve_effective_collection_name(subject_id, user_id)
    embeddings = get_embedding_function().embed_documents([document.page_content for document in documents])
    rows = [
        {
            "custom_id": ids[index],
            "embedding": embedding,
            "document": documents[index].page_content,
            "metadata": documents[index].metadata,
        }
        for index, embedding in enumerate(embeddings)
    ]
    return upsert_embedding_rows(collection_name, rows)


def upsert_documents(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    subject_id: str | None = None,
    user_id: str | None = None,
    visibility: str | None = None,
) -> int:
    _chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", "1000"))
    _chunk_overlap = chunk_overlap or int(os.getenv("CHUNK_OVERLAP", "200"))
    splitter = build_text_splitter(chunk_size=_chunk_size, chunk_overlap=_chunk_overlap)
    normalized_inputs: list[tuple[str, dict[str, Any]]] = []
    for index, text_value in enumerate(texts):
        text_content = str(text_value or "").strip()
        if not text_content:
            continue
        meta = dict(metadatas[index] if metadatas and index < len(metadatas) else {})
        normalized_inputs.append((text_content, meta))

    for _, meta in normalized_inputs:
        source_id = str(meta.get("source_id") or meta.get("source") or "").strip()
        doc_type = str(meta.get("doc_type") or "document").strip()
        if source_id:
            delete_source_documents(
                subject_id=subject_id,
                source_id=source_id,
                doc_type=doc_type,
                user_id=user_id,
            )

    documents: list[Document] = []
    ids: list[str] = []
    text_count = len(normalized_inputs)
    for text_index, (text_content, meta) in enumerate(normalized_inputs):
        chunks = splitter.split_text(text_content)
        source_id = str(meta.get("source_id") or meta.get("source") or uuid.uuid4()).strip()
        doc_type = str(meta.get("doc_type") or "document").strip()
        for chunk_index, chunk in enumerate(chunks):
            vector_id = _build_vector_id(doc_type, source_id, text_count, text_index, chunk_index)
            chunk_meta = _normalize_metadata(
                meta,
                subject_id=subject_id,
                text_index=text_index,
                chunk_index=chunk_index,
                vector_id=vector_id,
                user_id=user_id,
                visibility=visibility,
            )
            documents.append(Document(page_content=chunk, metadata=chunk_meta))
            ids.append(vector_id)
    if not documents:
        logger.warning("⚠️ 分块结果为空，无内容可入库")
        return 0
    _write_documents_to_collection(subject_id=subject_id, user_id=user_id, documents=documents, ids=ids)
    logger.info(f"✅ 幂等入库完成: {len(normalized_inputs)} 段原文 → {len(documents)} 个分块")
    return len(documents)


def ingest_documents(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    subject_id: str | None = None,
    user_id: str | None = None,
) -> int:
    _chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", "1000"))
    _chunk_overlap = chunk_overlap or int(os.getenv("CHUNK_OVERLAP", "200"))
    if metadatas:
        return upsert_documents(
            texts=texts,
            metadatas=metadatas,
            chunk_size=_chunk_size,
            chunk_overlap=_chunk_overlap,
            subject_id=subject_id,
            user_id=user_id,
        )

    splitter = build_text_splitter(chunk_size=_chunk_size, chunk_overlap=_chunk_overlap)
    documents: list[Document] = []
    ids: list[str] = []
    for index, text in enumerate(texts):
        chunks = splitter.split_text(text)
        meta = dict(metadatas[index] if metadatas and index < len(metadatas) else {})
        for chunk_index, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            chunk_meta = _normalize_metadata(
                meta,
                subject_id=subject_id,
                text_index=index,
                chunk_index=chunk_index,
                vector_id=chunk_id,
                user_id=user_id,
            )
            documents.append(Document(page_content=chunk, metadata=chunk_meta))
            ids.append(chunk_id)
    if not documents:
        logger.warning("⚠️ 分块结果为空，无内容可入库")
        return 0
    _write_documents_to_collection(subject_id=subject_id, user_id=user_id, documents=documents, ids=ids)
    logger.info(f"✅ 入库完成: {len(texts)} 段原文 → {len(documents)} 个分块")
    return len(documents)


def _search_collection_documents(
    *,
    collection_name: str,
    query: str,
    top_k: int,
    doc_types: list[str] | None,
    min_score: float | None,
    visibility: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    store = get_collection_by_name(collection_name)
    fetch_k = max(1, top_k * 3 if doc_types or min_score is not None else top_k)
    results = store.similarity_search_with_score(query=query, k=fetch_k)
    allowed_doc_types = {str(item) for item in list(doc_types or []) if str(item)}
    docs: list[dict[str, Any]] = []
    for index, (document, distance) in enumerate(results):
        metadata = dict(document.metadata or {})
        doc_type = str(metadata.get("doc_type") or "")
        if allowed_doc_types and doc_type and doc_type not in allowed_doc_types:
            continue
        score = _score_from_distance(float(distance))
        if min_score is not None and score < float(min_score):
            continue
        metadata.setdefault("visibility", visibility)
        if user_id:
            metadata.setdefault("user_id", str(user_id))
        raw_doc_id = metadata.get("vector_id") or metadata.get("id") or metadata.get("doc_id") or f"doc-{index}"
        docs.append(
            {
                "doc_id": str(raw_doc_id),
                "content": document.page_content,
                "metadata": metadata,
                "distance": float(distance),
                "score": score,
            }
        )
        if len(docs) >= top_k:
            break
    return docs


def _keyword_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", query.lower())
    terms: list[str] = []
    for term in raw_terms:
        normalized = term.strip()
        if not normalized or normalized in {"什么", "一下", "这个", "那个", "the", "and"}:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms[:8] or [query.lower().strip()]


def _keyword_score(content: str, terms: list[str]) -> float:
    normalized = content.lower()
    hits = sum(1 for term in terms if term and term in normalized)
    if hits <= 0:
        return 0.0
    return round(min(0.88, 0.52 + hits * 0.09), 4)


def _keyword_search_collection_documents(
    *,
    collection_name: str,
    query: str,
    top_k: int,
    doc_types: list[str] | None,
    min_score: float | None,
    visibility: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    if not pgvector_tables_ready():
        return []

    terms = [term for term in _keyword_terms(query) if term]
    where_parts = [f"collections.name = :collection_name"]
    params: dict[str, Any] = {"collection_name": collection_name, "limit": max(top_k * 4, top_k)}
    term_clauses: list[str] = []
    for index, term in enumerate(terms):
        key = f"term_{index}"
        term_clauses.append(f"LOWER(embeddings.document) LIKE :{key}")
        params[key] = f"%{term.lower()}%"
    if term_clauses:
        where_parts.append("(" + " OR ".join(term_clauses) + ")")

    stmt = text(
        f"""
        SELECT embeddings.id, embeddings.document, embeddings.cmetadata
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE {" AND ".join(where_parts)}
        LIMIT :limit
        """
    )
    allowed_doc_types = {str(item) for item in list(doc_types or []) if str(item)}
    docs: list[dict[str, Any]] = []
    with engine.begin() as connection:
        rows = connection.execute(stmt, params).mappings().all()

    for index, row in enumerate(rows):
        content = str(row.get("document") or "")
        metadata_raw = row.get("cmetadata") or {}
        if isinstance(metadata_raw, str):
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
        else:
            metadata = dict(metadata_raw)
        doc_type = str(metadata.get("doc_type") or "")
        if allowed_doc_types and doc_type and doc_type not in allowed_doc_types:
            continue
        score = _keyword_score(content, terms)
        if min_score is not None and score < float(min_score):
            continue
        metadata.setdefault("visibility", visibility)
        metadata["retrieval_source"] = "keyword_fallback"
        metadata["retrieval_warning"] = "vector_search_failed_keyword_fallback_used"
        if user_id:
            metadata.setdefault("user_id", str(user_id))
        raw_doc_id = metadata.get("vector_id") or metadata.get("id") or metadata.get("doc_id") or row.get("id")
        docs.append(
            {
                "doc_id": str(raw_doc_id or f"keyword-doc-{index}"),
                "content": content,
                "metadata": metadata,
                "distance": round(1.0 - score, 4),
                "score": score,
            }
        )
        if len(docs) >= top_k:
            break
    return sorted(docs, key=lambda item: float(item.get("score") or 0.0), reverse=True)[:top_k]


def _keyword_search_documents(
    *,
    query: str,
    top_k: int,
    subject_id: str | None,
    doc_types: list[str] | None,
    min_score: float | None,
    user_id: str | None,
) -> list[dict[str, Any]]:
    shared_docs = _keyword_search_collection_documents(
        collection_name=resolve_collection_name(subject_id),
        query=query,
        top_k=top_k,
        doc_types=doc_types,
        min_score=min_score,
        visibility="shared",
    )
    personal_docs: list[dict[str, Any]] = []
    if user_id:
        personal_docs = _keyword_search_collection_documents(
            collection_name=resolve_personal_collection_name(subject_id, user_id),
            query=query,
            top_k=top_k,
            doc_types=doc_types,
            min_score=min_score,
            visibility="personal",
            user_id=user_id,
        )
    return sorted(
        [*shared_docs, *personal_docs],
        key=lambda item: float(item.get("score") or 0.0),
        reverse=True,
    )[:top_k]


def search_documents(
    query: str,
    top_k: int = 5,
    subject_id: str | None = None,
    doc_types: list[str] | None = None,
    min_score: float | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        shared_docs = _search_collection_documents(
            collection_name=resolve_collection_name(subject_id),
            query=query,
            top_k=top_k,
            doc_types=doc_types,
            min_score=min_score,
            visibility="shared",
        )
        personal_docs: list[dict[str, Any]] = []
        if user_id:
            personal_docs = _search_collection_documents(
                collection_name=resolve_personal_collection_name(subject_id, user_id),
                query=query,
                top_k=top_k,
                doc_types=doc_types,
                min_score=min_score,
                visibility="personal",
                user_id=user_id,
            )
        docs = sorted(
            [*shared_docs, *personal_docs],
            key=lambda item: float(item.get("score") or 0.0),
            reverse=True,
        )[:top_k]
    except Exception as exc:
        logger.warning(
            f"⚠️ PGVector 向量检索失败，改用关键词兜底: {type(exc).__name__}"
        )
        docs = _keyword_search_documents(
            query=query,
            top_k=top_k,
            subject_id=subject_id,
            doc_types=doc_types,
            min_score=min_score,
            user_id=user_id,
        )
    logger.info(
        f"🔍 PGVector 检索完成: query='{query[:50]}…', "
        f"召回 {len(docs)} 篇"
    )
    return docs
