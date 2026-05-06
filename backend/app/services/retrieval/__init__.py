"""Deprecated compatibility package. Use app.services.rag."""

from app.services.rag.query_policy import build_contextual_query  # noqa: F401
from app.services.rag.retriever import (  # noqa: F401
    get_retrieval_contextual_query,
    retrieve,
    score_and_filter,
)
from app.services.rag.vector_store import (  # noqa: F401
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
from app.services.rag.embeddings import get_embedding_function  # noqa: F401


def get_chroma_client() -> None:
    raise RuntimeError("Chroma 已移除，请改用 PGVector 相关接口。")
