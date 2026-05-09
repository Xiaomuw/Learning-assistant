from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from langchain_postgres.vectorstores import DistanceStrategy

from app.infrastructure.llm.config import get_embedding_model_connection


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model_id: str
    dimension: int
    distance_strategy: str = "cosine"
    version: str = "v1"

    def as_metadata(self) -> dict[str, Any]:
        return {
            "embedding_provider": self.provider,
            "embedding_model": self.model_id,
            "embedding_dimension": self.dimension,
            "embedding_distance_strategy": self.distance_strategy,
            "embedding_profile_version": self.version,
        }


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def get_embedding_profile(*, observed_dimension: int | None = None) -> EmbeddingProfile:
    connection = get_embedding_model_connection()
    dimension = _env_int("PGVECTOR_EMBEDDING_DIMENSION", 0) or int(observed_dimension or 0)
    distance_strategy = (os.getenv("PGVECTOR_DISTANCE_STRATEGY") or "cosine").strip().lower() or "cosine"
    version = (
        os.getenv("EMBEDDING_PROFILE_VERSION")
        or f"{connection.provider}:{connection.model_id}:{dimension or 'unknown'}:{distance_strategy}"
    )
    return EmbeddingProfile(
        provider=connection.provider,
        model_id=connection.model_id,
        dimension=dimension,
        distance_strategy=distance_strategy,
        version=version,
    )


def get_pgvector_distance_strategy() -> DistanceStrategy:
    configured = get_embedding_profile().distance_strategy
    if configured in {"l2", "euclidean"}:
        return DistanceStrategy.EUCLIDEAN
    if configured in {"inner", "max_inner_product", "max-inner-product"}:
        return DistanceStrategy.MAX_INNER_PRODUCT
    return DistanceStrategy.COSINE
