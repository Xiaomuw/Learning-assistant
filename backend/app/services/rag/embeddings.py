from __future__ import annotations

from typing import Any

from app.infrastructure.llm.config import get_embedding_model_connection
from app.infrastructure.llm.provider import get_embeddings, validate_embedding_model_access


DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-2"


def get_embedding_function(default_model: str = DEFAULT_EMBEDDING_MODEL) -> Any:
    """Return the configured embedding client for RAG indexing and search."""
    return get_embeddings(default_model=default_model)


def check_embedding_ready(default_model: str = DEFAULT_EMBEDDING_MODEL) -> tuple[bool, str | None]:
    """Run the non-sensitive embedding access check used by health diagnostics."""
    return validate_embedding_model_access(model_id=default_model)


def describe_embedding_model_readiness() -> dict[str, Any]:
    """Return configuration-level embedding model readiness without making network calls."""
    connection = get_embedding_model_connection()
    issues: list[str] = []
    if not connection.model_id:
        issues.append("embedding_model_missing")
    if not connection.api_key:
        issues.append("embedding_api_key_missing")
    return {
        "embedding_model_ready": not issues,
        "embedding_model_error": ";".join(issues),
        "embedding_provider": connection.provider,
        "embedding_model": connection.model_id,
        "embedding_base_url": connection.base_url,
    }
