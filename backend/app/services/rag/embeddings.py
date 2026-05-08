from __future__ import annotations

from typing import Any

from app.infrastructure.llm.provider import get_embeddings, validate_embedding_model_access


DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-2"


def get_embedding_function(default_model: str = DEFAULT_EMBEDDING_MODEL) -> Any:
    """Return the configured embedding client for RAG indexing and search."""
    return get_embeddings(default_model=default_model)


def check_embedding_ready(default_model: str = DEFAULT_EMBEDDING_MODEL) -> dict[str, Any]:
    """Run the non-sensitive embedding access check used by health diagnostics."""
    return validate_embedding_model_access(model_id=default_model)
