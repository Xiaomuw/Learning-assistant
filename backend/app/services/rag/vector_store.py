from __future__ import annotations

import json
import os
import re
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_postgres import PGVector
from loguru import logger
from sqlalchemy import inspect, text

from app.infrastructure.db.database import engine, get_sqlalchemy_database_url
from app.infrastructure.db.repositories.knowledge_taxonomy import (
    delete_kb_chunks_by_source,
    save_kb_chunk_record,
)
from app.knowledge.concept_registry import ConceptMatch, get_concept_registry
from app.services.rag.embedding_profile import (
    EmbeddingProfile,
    get_embedding_profile,
    get_pgvector_distance_strategy,
)
from app.services.rag.embeddings import get_embedding_function
from app.services.rag.splitter import build_text_splitter
from app.shared.schemas.contracts import NotebookKnowledgeStatus

_store_cache: dict[str, PGVector] = {}
_embedding_table_columns_cache: set[str] | None = None
_embedding_table_index_cache: set[str] | None = None

PGVECTOR_COLLECTION_TABLE = "langchain_pg_collection"
PGVECTOR_EMBEDDING_TABLE = "langchain_pg_embedding"
VECTOR_ID_SOURCE_MAX_LENGTH = 64


@dataclass(frozen=True)
class IngestWriteSummary:
    inserted_chunks: int = 0
    mapped_chunks: int = 0
    unmapped_chunks: int = 0


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
        profile = get_embedding_profile()
        store = PGVector(
            embeddings=get_embedding_function(),
            collection_name=collection_name,
            connection=get_sqlalchemy_database_url(),
            embedding_length=profile.dimension or None,
            collection_metadata=profile.as_metadata(),
            distance_strategy=get_pgvector_distance_strategy(),
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


def _embedding_table_indexes() -> set[str]:
    global _embedding_table_index_cache
    if _embedding_table_index_cache is None:
        if not pgvector_tables_ready():
            return set()
        inspector = inspect(engine)
        _embedding_table_index_cache = {
            str(index["name"])
            for index in inspector.get_indexes(PGVECTOR_EMBEDDING_TABLE)
        }
    return _embedding_table_index_cache


def _pgvector_schema_health() -> dict[str, Any]:
    if not pgvector_tables_ready():
        return {
            "schema_ready": False,
            "index_ready": False,
            "schema_issues": ["pgvector_tables_missing"],
        }
    columns = _embedding_table_columns()
    indexes = _embedding_table_indexes()
    required_columns = {"collection_id", "embedding", "document", "cmetadata"}
    missing_columns = sorted(required_columns - columns)
    index_ready = any("custom_id" in name for name in indexes) and any("cmetadata" in name for name in indexes)
    issues: list[str] = []
    if missing_columns:
        issues.append("missing_columns:" + ",".join(missing_columns))
    if "custom_id" not in columns:
        issues.append("missing_custom_id")
    if not index_ready:
        issues.append("pgvector_indexes_incomplete")
    return {
        "schema_ready": not missing_columns,
        "index_ready": index_ready,
        "schema_issues": issues,
    }


def describe_vector_store_health() -> dict[str, Any]:
    health = _pgvector_schema_health()
    profile = get_embedding_profile()
    health["embedding_profile"] = profile.as_metadata()
    return health


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
    vector_health = describe_vector_store_health()
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
        schema_ready=bool(vector_health.get("schema_ready")),
        index_ready=bool(vector_health.get("index_ready")),
        schema_issues=list(vector_health.get("schema_issues") or []),
        embedding_profile=dict(vector_health.get("embedding_profile") or {}),
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


def _custom_id_unique_index_ready() -> bool:
    return any(
        "custom_id" in name and (name.startswith("uq_") or "uniq" in name or "unique" in name)
        for name in _embedding_table_indexes()
    )


def _sync_collection_embedding_profile(
    *,
    collection_id: Any,
    profile: EmbeddingProfile,
) -> None:
    collection_columns = {
        str(column["name"])
        for column in inspect(engine).get_columns(PGVECTOR_COLLECTION_TABLE)
    }
    if "cmetadata" not in collection_columns:
        return
    stmt = text(
        f"""
        UPDATE {PGVECTOR_COLLECTION_TABLE}
        SET cmetadata = CAST(:metadata AS JSONB)
        WHERE uuid = :collection_id
        """
    )
    with engine.begin() as connection:
        connection.execute(
            stmt,
            {
                "collection_id": collection_id,
                "metadata": json.dumps(profile.as_metadata(), ensure_ascii=False),
            },
        )


def _embedding_vector(row: dict[str, Any]) -> list[float]:
    raw = list(row.get("embedding") or [])
    if not raw:
        raise ValueError("embedding 不能为空")
    return [float(value) for value in raw]


def _embedding_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(value) for value in embedding) + "]"


def _validate_embedding_dimensions(rows: list[dict[str, Any]]) -> tuple[list[list[float]], EmbeddingProfile]:
    vectors = [_embedding_vector(row) for row in rows]
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise ValueError(f"同一批向量维度不一致: {sorted(dimensions)}")
    observed_dimension = dimensions.pop()
    profile = get_embedding_profile(observed_dimension=observed_dimension)
    if profile.dimension and observed_dimension != profile.dimension:
        raise ValueError(
            "embedding 维度与当前 profile 不一致: "
            f"observed={observed_dimension}, expected={profile.dimension}"
        )
    return vectors, profile


def upsert_embedding_rows(collection_name: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    vectors, profile = _validate_embedding_dimensions(rows)
    ensure_collection_ready(collection_name)
    has_custom_id_column = "custom_id" in _embedding_table_columns()
    can_on_conflict_custom_id = has_custom_id_column and _custom_id_unique_index_ready()
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
        collection_columns = {
            str(column["name"])
            for column in inspect(engine).get_columns(PGVECTOR_COLLECTION_TABLE)
        }
        if "cmetadata" in collection_columns:
            connection.execute(
                text(
                    f"""
                    UPDATE {PGVECTOR_COLLECTION_TABLE}
                    SET cmetadata = CAST(:metadata AS JSONB)
                    WHERE uuid = :collection_id
                    """
                ),
                {
                    "collection_id": collection_id,
                    "metadata": json.dumps(profile.as_metadata(), ensure_ascii=False),
                },
            )
        written = 0
        for index, row in enumerate(rows):
            custom_id = str(row.get("custom_id") or row.get("id") or uuid.uuid4())
            embedding = vectors[index]
            document = str(row.get("document", "") or "")
            metadata = dict(row.get("metadata") or {})
            metadata.setdefault("vector_id", custom_id)
            metadata.update(profile.as_metadata())
            embedding_literal = _embedding_literal(embedding)
            if has_custom_id_column:
                params = {
                    "id": str(uuid.uuid4()),
                    "collection_id": collection_id,
                    "embedding": embedding_literal,
                    "document": document,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                    "custom_id": custom_id,
                }
                if can_on_conflict_custom_id:
                    connection.execute(
                        text(
                            f"""
                            INSERT INTO {PGVECTOR_EMBEDDING_TABLE}
                                (id, collection_id, embedding, document, cmetadata, custom_id)
                            VALUES
                                (:id, :collection_id, CAST(:embedding AS vector), :document, CAST(:metadata AS JSONB), :custom_id)
                            ON CONFLICT (collection_id, custom_id)
                            WHERE custom_id IS NOT NULL AND custom_id <> ''
                            DO UPDATE SET
                                embedding = EXCLUDED.embedding,
                                document = EXCLUDED.document,
                                cmetadata = EXCLUDED.cmetadata
                            """
                        ),
                        params,
                    )
                else:
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
                        params,
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


def _matches_metadata_filter(metadata: dict[str, Any], metadata_filter: dict[str, Any] | None) -> bool:
    if not metadata_filter:
        return True
    for key, expected in dict(metadata_filter).items():
        if expected is None or expected == "" or expected == []:
            continue
        actual = metadata.get(str(key))
        if isinstance(expected, (list, tuple, set)):
            expected_values = {str(item) for item in expected if str(item)}
            if expected_values and str(actual) not in expected_values:
                return False
        elif str(actual) != str(expected):
            return False
    return True


def _metadata_filter_without(metadata_filter: dict[str, Any] | None, *keys: str) -> dict[str, Any] | None:
    if not metadata_filter:
        return None
    excluded = {key for key in keys}
    filtered: dict[str, Any] = {}
    for key, value in dict(metadata_filter).items():
        if key in excluded:
            continue
        if value is None or value == "" or value == [] or value == ():
            continue
        filtered[key] = value
    return filtered or None


def _pgvector_metadata_filter(
    *,
    doc_types: list[str] | None,
    metadata_filter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    allowed_doc_types = [str(item) for item in list(doc_types or []) if str(item)]
    if allowed_doc_types:
        clauses.append({"doc_type": {"$in": allowed_doc_types}})
    for key, expected in dict(metadata_filter or {}).items():
        key_text = str(key)
        if not key_text.isidentifier():
            return None
        if expected is None or expected == "" or expected == []:
            continue
        if isinstance(expected, (list, tuple, set)):
            values = [item for item in expected if str(item)]
            if values:
                clauses.append({key_text: {"$in": values}})
        else:
            clauses.append({key_text: expected})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _dedupe_and_rank_documents(docs: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for doc in docs:
        metadata = dict(doc.get("metadata") or {})
        key = str(
            metadata.get("vector_id")
            or metadata.get("source_id")
            or doc.get("doc_id")
            or _content_hash(str(doc.get("content") or ""))
        )
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = doc
            continue
        existing_meta = dict(existing.get("metadata") or {})
        existing_rank = float(existing.get("score") or 0.0) + (0.02 if existing_meta.get("visibility") == "personal" else 0.0)
        candidate_rank = float(doc.get("score") or 0.0) + (0.02 if metadata.get("visibility") == "personal" else 0.0)
        if candidate_rank > existing_rank:
            best_by_key[key] = doc
    return sorted(
        best_by_key.values(),
        key=lambda item: float(item.get("score") or 0.0)
        + (0.02 if (item.get("metadata") or {}).get("visibility") == "personal" else 0.0),
        reverse=True,
    )[:top_k]


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


def _source_file_from_metadata(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("source_file")
        or metadata.get("source_id")
        or metadata.get("source")
        or "manual"
    )


def _optional_page(value: Any) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_start(metadata: dict[str, Any]) -> int | None:
    return _optional_page(metadata.get("page_start") or metadata.get("page"))


def _page_end(metadata: dict[str, Any]) -> int | None:
    return _optional_page(metadata.get("page_end") or metadata.get("page"))


def _content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _concept_match_for_chunk(
    chunk: str,
    metadata: dict[str, Any],
    *,
    subject_id: str | None,
) -> ConceptMatch:
    registry = get_concept_registry()
    explicit_concept_id = str(metadata.get("concept_id") or "").strip()
    if explicit_concept_id:
        concept = registry.get_concept(explicit_concept_id)
        if concept is not None:
            if subject_id and concept.subject_id != subject_id:
                logger.warning(
                    "⚠️ metadata.concept_id 与目标 subject 不一致，已忽略显式绑定: "
                    f"concept={concept.concept_id}, concept_subject={concept.subject_id}, target={subject_id}"
                )
                return registry.match_chunk(chunk, subject_id=subject_id, metadata={**metadata, "concept_id": ""})
            return ConceptMatch(
                subject_id=concept.subject_id,
                subject_name=concept.subject_name,
                chapter_id=concept.chapter_id,
                topic_id=concept.topic_id,
                concept_id=concept.concept_id,
                concept_name=concept.concept_name,
                confidence=1.0,
                status="matched",
                candidates=[{**concept.metadata(), "confidence": 1.0, "matched_terms": ["metadata.concept_id"]}],
            )
    return registry.match_chunk(chunk, subject_id=subject_id, metadata=metadata)


def _metadata_with_concept_mapping(metadata: dict[str, Any], match: ConceptMatch) -> dict[str, Any]:
    mapped = dict(metadata)
    mapped.update(
        {
            "source_file": _source_file_from_metadata(metadata),
            "page_start": _page_start(metadata),
            "page_end": _page_end(metadata),
            "concept_mapping_status": match.status,
            "concept_mapping_confidence": round(float(match.confidence or 0.0), 4),
            "concept_candidates": list(match.candidates[:5]),
        }
    )
    if match.status != "matched" or not match.concept_id:
        mapped.update(
            {
                "chapter_id": "",
                "chapter_name": "",
                "topic_id": "",
                "topic_name": "",
                "concept_id": "",
                "concept_name": "",
                "mapping_status": "unmapped",
            }
        )
        return mapped

    concept = get_concept_registry().get_concept(match.concept_id)
    if concept is None:
        mapped.update(
            {
                "chapter_id": "",
                "chapter_name": "",
                "topic_id": "",
                "topic_name": "",
                "concept_id": "",
                "concept_name": "",
                "mapping_status": "unmapped",
            }
        )
        return mapped

    mapped.update(
        {
            "subject_name": concept.subject_name,
            "chapter_id": concept.chapter_id,
            "chapter_name": concept.chapter_name,
            "topic_id": concept.topic_id,
            "topic_name": concept.topic_name,
            "concept_id": concept.concept_id,
            "concept_name": concept.concept_name,
            "knowledge_point": mapped.get("knowledge_point") or concept.concept_name,
            "mapping_status": "mapped",
        }
    )
    return mapped


def _record_kb_chunk_mapping(
    *,
    vector_id: str,
    metadata: dict[str, Any],
    content: str,
) -> None:
    save_kb_chunk_record(
        {
            "id": vector_id,
            "vector_id": vector_id,
            "subject_id": metadata.get("subject_id") or "",
            "subject_name": metadata.get("subject_name") or "",
            "chapter_id": metadata.get("chapter_id") or "",
            "chapter_name": metadata.get("chapter_name") or "",
            "topic_id": metadata.get("topic_id") or "",
            "topic_name": metadata.get("topic_name") or "",
            "concept_id": metadata.get("concept_id") or "",
            "concept_name": metadata.get("concept_name") or "",
            "source_file": metadata.get("source_file") or _source_file_from_metadata(metadata),
            "page_start": metadata.get("page_start"),
            "page_end": metadata.get("page_end"),
            "mapping_status": metadata.get("mapping_status") or "unmapped",
            "content_hash": _content_hash(content),
            "content_text": content,
            "metadata_json": metadata,
        }
    )


def _build_vector_id(doc_type: str, source_id: str, text_count: int, text_index: int, chunk_index: int) -> str:
    source_part = _safe_vector_id_part(source_id)
    doc_type_part = _safe_vector_id_part(doc_type, max_length=36)
    if doc_type == "question_bank":
        return f"question_bank:{source_part}:{chunk_index}"
    return f"{doc_type_part}:{source_part}:{text_index}:{chunk_index}"


def _safe_vector_id_part(value: str, *, max_length: int = VECTOR_ID_SOURCE_MAX_LENGTH) -> str:
    raw = str(value or "").strip()
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("_.-")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    if not normalized:
        return digest
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max(8, max_length - 13)]}_{digest}"


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


def upsert_documents_with_summary(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    subject_id: str | None = None,
    user_id: str | None = None,
    visibility: str | None = None,
) -> IngestWriteSummary:
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
            try:
                delete_kb_chunks_by_source(
                    subject_id=subject_id,
                    source_file=_source_file_from_metadata(meta),
                    source_id=source_id,
                    doc_type=doc_type,
                    user_id=user_id or None,
                )
            except Exception as exc:  # noqa: BLE001 - stale mapping cleanup should not block ingest
                logger.warning(f"⚠️ kb_chunk 旧映射清理失败，已继续入库: {exc.__class__.__name__}")

    documents: list[Document] = []
    ids: list[str] = []
    chunk_mappings: list[tuple[str, dict[str, Any], str]] = []
    text_count = len(normalized_inputs)
    mapped_chunks = 0
    unmapped_chunks = 0
    for text_index, (text_content, meta) in enumerate(normalized_inputs):
        chunks = splitter.split_text(text_content)
        source_id = str(meta.get("source_id") or meta.get("source") or uuid.uuid4()).strip()
        doc_type = str(meta.get("doc_type") or "document").strip()
        for chunk_index, chunk in enumerate(chunks):
            vector_id = _build_vector_id(doc_type, source_id, text_count, text_index, chunk_index)
            base_meta = _normalize_metadata(
                meta,
                subject_id=subject_id,
                text_index=text_index,
                chunk_index=chunk_index,
                vector_id=vector_id,
                user_id=user_id,
                visibility=visibility,
            )
            match = _concept_match_for_chunk(chunk, base_meta, subject_id=subject_id)
            chunk_meta = _metadata_with_concept_mapping(base_meta, match)
            if chunk_meta.get("mapping_status") != "mapped":
                unmapped_chunks += 1
            else:
                mapped_chunks += 1
            documents.append(Document(page_content=chunk, metadata=chunk_meta))
            ids.append(vector_id)
            chunk_mappings.append((vector_id, chunk_meta, chunk))
    if not documents:
        logger.warning(
            "⚠️ 分块结果为空，无内容写入主知识库 "
            f"(mapped={mapped_chunks}, unmapped={unmapped_chunks})"
        )
        return IngestWriteSummary(
            inserted_chunks=0,
            mapped_chunks=mapped_chunks,
            unmapped_chunks=unmapped_chunks,
        )
    inserted_chunks = _write_documents_to_collection(
        subject_id=subject_id,
        user_id=user_id,
        documents=documents,
        ids=ids,
    )
    try:
        for vector_id, chunk_meta, chunk in chunk_mappings:
            _record_kb_chunk_mapping(vector_id=vector_id, metadata=chunk_meta, content=chunk)
    except Exception:
        logger.exception("❌ kb_chunk 映射记录写入失败，正在清理本次已写入向量")
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
        raise
    logger.info(
        f"✅ 幂等入库完成: {len(normalized_inputs)} 段原文 → "
        f"{mapped_chunks} 个 mapped 分块，{unmapped_chunks} 个 unmapped 分块，"
        f"{inserted_chunks} 个分块写入向量库"
    )
    return IngestWriteSummary(
        inserted_chunks=inserted_chunks,
        mapped_chunks=mapped_chunks,
        unmapped_chunks=unmapped_chunks,
    )


def upsert_documents(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    subject_id: str | None = None,
    user_id: str | None = None,
    visibility: str | None = None,
) -> int:
    summary = upsert_documents_with_summary(
        texts=texts,
        metadatas=metadatas,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        subject_id=subject_id,
        user_id=user_id,
        visibility=visibility,
    )
    return summary.inserted_chunks


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
    effective_metadatas = metadatas if metadatas is not None else [{} for _ in texts]
    return upsert_documents(
        texts=texts,
        metadatas=effective_metadatas,
        chunk_size=_chunk_size,
        chunk_overlap=_chunk_overlap,
        subject_id=subject_id,
        user_id=user_id,
    )


def _search_collection_documents(
    *,
    collection_name: str,
    query: str,
    top_k: int,
    doc_types: list[str] | None,
    min_score: float | None,
    metadata_filter: dict[str, Any] | None,
    visibility: str,
    user_id: str | None = None,
    retrieval_stage: str = "vector",
) -> list[dict[str, Any]]:
    store = get_collection_by_name(collection_name)
    pg_filter = _pgvector_metadata_filter(doc_types=doc_types, metadata_filter=metadata_filter)
    filter_mode = "pgvector" if pg_filter else ("post_filter" if doc_types or metadata_filter else "none")
    fetch_k = max(1, top_k * (3 if pg_filter else 10 if doc_types or min_score is not None or metadata_filter else 1))
    try:
        results = store.similarity_search_with_score(query=query, k=fetch_k, filter=pg_filter)
    except Exception:
        if not pg_filter:
            raise
        filter_mode = "post_filter"
        results = store.similarity_search_with_score(query=query, k=max(fetch_k, top_k * 12))
    allowed_doc_types = {str(item) for item in list(doc_types or []) if str(item)}
    docs: list[dict[str, Any]] = []
    for index, (document, distance) in enumerate(results):
        metadata = dict(document.metadata or {})
        doc_type = str(metadata.get("doc_type") or "")
        if allowed_doc_types and (not doc_type or doc_type not in allowed_doc_types):
            continue
        if not _matches_metadata_filter(metadata, metadata_filter):
            continue
        score = _score_from_distance(float(distance))
        if min_score is not None and score < float(min_score):
            continue
        metadata.setdefault("visibility", visibility)
        metadata.setdefault("retrieval_stage", retrieval_stage)
        metadata.setdefault("filter_mode", filter_mode)
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
    return round(min(0.9, 0.61 + hits * 0.07), 4)


def _append_keyword_metadata_sql_filters(
    *,
    where_parts: list[str],
    params: dict[str, Any],
    doc_types: list[str] | None,
    metadata_filter: dict[str, Any] | None,
) -> None:
    allowed_doc_types = [str(item) for item in list(doc_types or []) if str(item)]
    if allowed_doc_types:
        where_parts.append("embeddings.cmetadata->>'doc_type' = ANY(:doc_types)")
        params["doc_types"] = allowed_doc_types
    for index, (key, expected) in enumerate(dict(metadata_filter or {}).items()):
        key_text = str(key)
        if not key_text.isidentifier():
            continue
        if expected is None or expected == "" or expected == []:
            continue
        param_key = f"metadata_{index}"
        if isinstance(expected, (list, tuple, set)):
            values = [str(item) for item in expected if str(item)]
            if values:
                where_parts.append(f"embeddings.cmetadata->>'{key_text}' = ANY(:{param_key})")
                params[param_key] = values
        else:
            where_parts.append(f"embeddings.cmetadata->>'{key_text}' = :{param_key}")
            params[param_key] = str(expected)


def _keyword_search_collection_documents(
    *,
    collection_name: str,
    query: str,
    top_k: int,
    doc_types: list[str] | None,
    min_score: float | None,
    metadata_filter: dict[str, Any] | None,
    visibility: str,
    user_id: str | None = None,
    retrieval_stage: str = "keyword_fallback",
) -> list[dict[str, Any]]:
    if not pgvector_tables_ready():
        return []

    terms = [term for term in _keyword_terms(query) if term]
    where_parts = [f"collections.name = :collection_name"]
    params: dict[str, Any] = {"collection_name": collection_name, "limit": max(top_k * 8, top_k)}
    term_clauses: list[str] = []
    for index, term in enumerate(terms):
        key = f"term_{index}"
        term_clauses.append(f"LOWER(embeddings.document) LIKE :{key}")
        params[key] = f"%{term.lower()}%"
    if term_clauses:
        where_parts.append("(" + " OR ".join(term_clauses) + ")")
    _append_keyword_metadata_sql_filters(
        where_parts=where_parts,
        params=params,
        doc_types=doc_types,
        metadata_filter=metadata_filter,
    )

    stmt = text(
        f"""
        SELECT embeddings.id, embeddings.document, embeddings.cmetadata
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE {" AND ".join(where_parts)}
        ORDER BY embeddings.id
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
        if allowed_doc_types and (not doc_type or doc_type not in allowed_doc_types):
            continue
        if not _matches_metadata_filter(metadata, metadata_filter):
            continue
        score = _keyword_score(content, terms)
        if min_score is not None and score < float(min_score):
            continue
        metadata.setdefault("visibility", visibility)
        metadata.setdefault("retrieval_stage", retrieval_stage)
        metadata.setdefault("filter_mode", "sql")
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
    metadata_filter: dict[str, Any] | None,
    user_id: str | None,
) -> list[dict[str, Any]]:
    shared_docs = _keyword_search_collection_documents(
        collection_name=resolve_collection_name(subject_id),
        query=query,
        top_k=top_k,
        doc_types=doc_types,
        min_score=min_score,
        metadata_filter=metadata_filter,
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
            metadata_filter=metadata_filter,
            visibility="personal",
            user_id=user_id,
        )
    return _dedupe_and_rank_documents([*shared_docs, *personal_docs], top_k=top_k)


def search_documents(
    query: str,
    top_k: int = 5,
    subject_id: str | None = None,
    doc_types: list[str] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    min_score: float | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        docs = _staged_vector_search_documents(
            query=query,
            top_k=top_k,
            subject_id=subject_id,
            doc_types=doc_types,
            metadata_filter=metadata_filter,
            min_score=min_score,
            user_id=user_id,
        )
        if not docs:
            docs = _keyword_search_documents(
                query=query,
                top_k=top_k,
                subject_id=subject_id,
                doc_types=doc_types,
                min_score=min_score,
                metadata_filter=metadata_filter,
                user_id=user_id,
            )
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
            metadata_filter=metadata_filter,
            user_id=user_id,
        )
    logger.info(
        f"🔍 PGVector 检索完成: query='{query[:50]}…', "
        f"召回 {len(docs)} 篇"
    )
    return docs


def _staged_vector_search_documents(
    *,
    query: str,
    top_k: int,
    subject_id: str | None,
    doc_types: list[str] | None,
    metadata_filter: dict[str, Any] | None,
    min_score: float | None,
    user_id: str | None,
) -> list[dict[str, Any]]:
    stages: list[tuple[str, dict[str, Any] | None]] = [("strict", dict(metadata_filter or {}) or None)]
    if metadata_filter and metadata_filter.get("concept_id"):
        topic_filter = _metadata_filter_without(metadata_filter, "concept_id")
        if topic_filter != metadata_filter:
            stages.append(("relaxed_topic", topic_filter))
    if metadata_filter and (metadata_filter.get("concept_id") or metadata_filter.get("topic_id")):
        subject_filter = _metadata_filter_without(metadata_filter, "concept_id", "topic_id")
        if subject_filter != stages[-1][1]:
            stages.append(("subject_doc_type", subject_filter))

    seen_stage_filters: set[str] = set()
    for stage, stage_filter in stages:
        filter_key = json.dumps(stage_filter or {}, ensure_ascii=False, sort_keys=True)
        if filter_key in seen_stage_filters:
            continue
        seen_stage_filters.add(filter_key)
        shared_docs = _search_collection_documents(
            collection_name=resolve_collection_name(subject_id),
            query=query,
            top_k=top_k,
            doc_types=doc_types,
            min_score=min_score,
            metadata_filter=stage_filter,
            visibility="shared",
            retrieval_stage=stage,
        )
        personal_docs: list[dict[str, Any]] = []
        if user_id:
            personal_docs = _search_collection_documents(
                collection_name=resolve_personal_collection_name(subject_id, user_id),
                query=query,
                top_k=top_k,
                doc_types=doc_types,
                min_score=min_score,
                metadata_filter=stage_filter,
                visibility="personal",
                user_id=user_id,
                retrieval_stage=stage,
            )
        docs = _dedupe_and_rank_documents([*shared_docs, *personal_docs], top_k=top_k)
        if docs:
            return docs
    return []
