"""
Reconcile PGVector and kb_chunk mappings.

只读扫描默认不修复数据，用于发现：
- kb_chunk 有记录但 PGVector 没有对应 vector_id
- PGVector 有向量但 kb_chunk 没有映射
- PGVector 中重复 custom_id/vector_id
- 同一 collection 中混合 embedding dimension
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from app.infrastructure.db.database import engine  # noqa: E402
from app.services.rag.vector_store import (
    PGVECTOR_COLLECTION_TABLE,
    PGVECTOR_EMBEDDING_TABLE,
    get_collection_prefix,
    pgvector_tables_ready,
    resolve_collection_name,
)  # noqa: E402


def _rows(statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        return [dict(row) for row in connection.execute(text(statement), params).mappings().all()]


def scan(subject_id: str | None, *, limit: int) -> dict[str, Any]:
    collection_name = resolve_collection_name(subject_id)
    if not pgvector_tables_ready():
        return {
            "collection_name": collection_name,
            "pgvector_ready": False,
            "embedding_count": 0,
            "kb_chunk_count": 0,
            "doc_type_counts": {},
            "is_empty_collection": True,
            "issues": ["pgvector_tables_missing"],
        }

    if subject_id:
        return _scan_collection(collection_name, subject_id=subject_id, limit=limit)

    collections = _learning_collections(limit=1000)
    collection_reports = [
        _scan_collection(str(row["name"]), subject_id=None, limit=limit)
        for row in collections
    ]
    issues = sorted({issue for report in collection_reports for issue in list(report.get("issues") or [])})
    embedding_count = sum(int(report.get("embedding_count") or 0) for report in collection_reports)
    kb_chunk_count = sum(int(report.get("kb_chunk_count") or 0) for report in collection_reports)
    return {
        "pgvector_ready": True,
        "collection_count": len(collection_reports),
        "embedding_count": embedding_count,
        "kb_chunk_count": kb_chunk_count,
        "doc_type_counts": _merge_doc_type_counts(collection_reports),
        "is_empty_collection": embedding_count == 0,
        "issues": issues,
        "collections": collection_reports,
    }


def _learning_collections(*, limit: int) -> list[dict[str, Any]]:
    return _rows(
        f"""
        SELECT name
        FROM {PGVECTOR_COLLECTION_TABLE}
        WHERE name LIKE :pattern
        ORDER BY name
        LIMIT :limit
        """,
        {"pattern": f"{get_collection_prefix()}_%", "limit": max(1, int(limit))},
    )


def _scan_collection(collection_name: str, *, subject_id: str | None, limit: int) -> dict[str, Any]:
    params = {"collection_name": collection_name, "limit": max(1, min(int(limit or 100), 1000))}
    content_summary = _collection_content_summary(collection_name, subject_id=subject_id)
    duplicate_ids = _rows(
        f"""
        SELECT COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id') AS vector_id,
               COUNT(*) AS count
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        GROUP BY COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id')
        HAVING COUNT(*) > 1
        LIMIT :limit
        """,
        params,
    )
    vector_without_chunk = _rows(
        f"""
        SELECT COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id') AS vector_id,
               embeddings.cmetadata->>'source_id' AS source_id,
               embeddings.cmetadata->>'doc_type' AS doc_type
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        LEFT JOIN kb_chunk ON kb_chunk.vector_id = COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id')
        WHERE collections.name = :collection_name
          AND kb_chunk.id IS NULL
        LIMIT :limit
        """,
        params,
    )
    chunk_without_vector = _rows(
        f"""
        SELECT kb_chunk.vector_id, kb_chunk.source_file, kb_chunk.mapping_status
        FROM kb_chunk
        LEFT JOIN {PGVECTOR_EMBEDDING_TABLE} AS embeddings
          ON kb_chunk.vector_id = COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id')
        LEFT JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE kb_chunk.subject_id = COALESCE(:subject_id, kb_chunk.subject_id)
          AND embeddings.id IS NULL
        LIMIT :limit
        """,
        {**params, "subject_id": subject_id},
    )
    dimensions = _rows(
        f"""
        SELECT vector_dims(embeddings.embedding) AS embedding_dimension,
               embeddings.cmetadata->>'embedding_provider' AS embedding_provider,
               embeddings.cmetadata->>'embedding_model' AS embedding_model,
               embeddings.cmetadata->>'embedding_profile_version' AS embedding_profile_version,
               COUNT(*) AS count
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        GROUP BY 1, 2, 3, 4
        ORDER BY count DESC
        """,
        params,
    )
    missing_custom_id = _rows(
        f"""
        SELECT embeddings.id,
               embeddings.cmetadata->>'vector_id' AS vector_id,
               embeddings.cmetadata->>'source_id' AS source_id,
               embeddings.cmetadata->>'doc_type' AS doc_type
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
          AND (embeddings.custom_id IS NULL OR embeddings.custom_id = '')
        LIMIT :limit
        """,
        params,
    )
    missing_doc_type = _rows(
        f"""
        SELECT COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id') AS vector_id,
               embeddings.cmetadata->>'source_id' AS source_id
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
          AND (embeddings.cmetadata->>'doc_type' IS NULL OR embeddings.cmetadata->>'doc_type' = '')
        LIMIT :limit
        """,
        params,
    )
    issues: list[str] = []
    if duplicate_ids:
        issues.append("duplicate_vector_ids")
    if missing_custom_id:
        issues.append("missing_custom_id")
    if missing_doc_type:
        issues.append("missing_doc_type")
    if vector_without_chunk:
        issues.append("vectors_without_kb_chunk")
    if chunk_without_vector:
        issues.append("kb_chunks_without_vector")
    if len({row.get("embedding_dimension") for row in dimensions if row.get("embedding_dimension")}) > 1:
        issues.append("mixed_embedding_dimensions")
    if content_summary["is_empty_collection"]:
        issues.append("empty_collection")
    return {
        "collection_name": collection_name,
        "pgvector_ready": True,
        **content_summary,
        "issues": issues,
        "duplicate_vector_ids": duplicate_ids,
        "missing_custom_id": missing_custom_id,
        "missing_doc_type": missing_doc_type,
        "vectors_without_kb_chunk": vector_without_chunk,
        "kb_chunks_without_vector": chunk_without_vector,
        "embedding_dimensions": dimensions,
    }


def _collection_content_summary(collection_name: str, *, subject_id: str | None) -> dict[str, Any]:
    params = {"collection_name": collection_name}
    embedding_count = _count_first(
        _rows(
            f"""
            SELECT COUNT(*) AS embedding_count
            FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
            JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
              ON embeddings.collection_id = collections.uuid
            WHERE collections.name = :collection_name
            """,
            params,
        ),
        "embedding_count",
    )
    doc_type_rows = _rows(
        f"""
        SELECT COALESCE(NULLIF(embeddings.cmetadata->>'doc_type', ''), 'unknown') AS doc_type,
               COUNT(*) AS count
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        GROUP BY doc_type
        ORDER BY count DESC, doc_type
        """,
        params,
    )
    if subject_id:
        kb_chunk_count = _count_first(
            _rows(
                """
                SELECT COUNT(*) AS kb_chunk_count
                FROM kb_chunk
                WHERE subject_id = :subject_id
                """,
                {"subject_id": subject_id},
            ),
            "kb_chunk_count",
        )
    else:
        kb_chunk_count = _count_first(
            _rows(
                f"""
                SELECT COUNT(kb_chunk.id) AS kb_chunk_count
                FROM kb_chunk
                JOIN {PGVECTOR_EMBEDDING_TABLE} AS embeddings
                  ON kb_chunk.vector_id = COALESCE(embeddings.custom_id, embeddings.cmetadata->>'vector_id')
                JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
                  ON embeddings.collection_id = collections.uuid
                WHERE collections.name = :collection_name
                """,
                params,
            ),
            "kb_chunk_count",
        )
    doc_type_counts = {
        str(row.get("doc_type") or "unknown"): int(row.get("count") or 0)
        for row in doc_type_rows
    }
    return {
        "embedding_count": embedding_count,
        "kb_chunk_count": kb_chunk_count,
        "doc_type_counts": doc_type_counts,
        "is_empty_collection": embedding_count == 0,
    }


def _count_first(rows: list[dict[str, Any]], key: str) -> int:
    if not rows:
        return 0
    return int(rows[0].get(key) or 0)


def _merge_doc_type_counts(collection_reports: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for report in collection_reports:
        counter.update(
            {
                str(doc_type): int(count or 0)
                for doc_type, count in dict(report.get("doc_type_counts") or {}).items()
            }
        )
    return dict(sorted(counter.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描 PGVector 与 kb_chunk 映射一致性")
    parser.add_argument("--subject-id", default=None, help="只扫描指定 subject 对应 collection")
    parser.add_argument("--limit", type=int, default=100, help="每类问题最多返回多少条")
    args = parser.parse_args()

    result = scan(args.subject_id, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
