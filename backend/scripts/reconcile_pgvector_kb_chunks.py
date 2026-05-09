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
import json
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

from app.infrastructure.db.database import engine
from app.services.rag.vector_store import (
    PGVECTOR_COLLECTION_TABLE,
    PGVECTOR_EMBEDDING_TABLE,
    pgvector_tables_ready,
    resolve_collection_name,
)


def _rows(statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        return [dict(row) for row in connection.execute(text(statement), params).mappings().all()]


def scan(subject_id: str | None, *, limit: int) -> dict[str, Any]:
    collection_name = resolve_collection_name(subject_id)
    if not pgvector_tables_ready():
        return {
            "collection_name": collection_name,
            "pgvector_ready": False,
            "issues": ["pgvector_tables_missing"],
        }

    params = {"collection_name": collection_name, "limit": max(1, min(int(limit or 100), 1000))}
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
        SELECT embeddings.cmetadata->>'embedding_dimension' AS embedding_dimension,
               COUNT(*) AS count
        FROM {PGVECTOR_EMBEDDING_TABLE} AS embeddings
        JOIN {PGVECTOR_COLLECTION_TABLE} AS collections
          ON embeddings.collection_id = collections.uuid
        WHERE collections.name = :collection_name
        GROUP BY embeddings.cmetadata->>'embedding_dimension'
        ORDER BY count DESC
        """,
        params,
    )
    issues: list[str] = []
    if duplicate_ids:
        issues.append("duplicate_vector_ids")
    if vector_without_chunk:
        issues.append("vectors_without_kb_chunk")
    if chunk_without_vector:
        issues.append("kb_chunks_without_vector")
    if len([row for row in dimensions if row.get("embedding_dimension")]) > 1:
        issues.append("mixed_embedding_dimensions")
    return {
        "collection_name": collection_name,
        "pgvector_ready": True,
        "issues": issues,
        "duplicate_vector_ids": duplicate_ids,
        "vectors_without_kb_chunk": vector_without_chunk,
        "kb_chunks_without_vector": chunk_without_vector,
        "embedding_dimensions": dimensions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描 PGVector 与 kb_chunk 映射一致性")
    parser.add_argument("--subject-id", default=None, help="只扫描指定 subject 对应 collection")
    parser.add_argument("--limit", type=int, default=100, help="每类问题最多返回多少条")
    args = parser.parse_args()

    load_dotenv()
    result = scan(args.subject_id, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
