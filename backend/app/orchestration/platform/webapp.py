"""
LangGraph Platform lifespan app.

The platform sidecar does not mount the public FastAPI business routes. Its
lifespan only prepares shared infrastructure that graph nodes need.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from loguru import logger

load_dotenv()

from app.infrastructure.config.validation import (  # noqa: E402
    collect_environment_warnings,
    validate_startup_environment,
)
from app.infrastructure.db.database import current_database_backend, ensure_postgres_extensions  # noqa: E402
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: E402
from app.infrastructure.llm.langsmith import initialize_langsmith  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402
from app.infrastructure.mcp import initialize_mcp  # noqa: E402
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID  # noqa: E402


ensure_model_env_aliases()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 LangGraph Platform sidecar starting ...")

    validate_startup_environment()
    for warning in collect_environment_warnings():
        logger.warning(f"⚠️ {warning}")

    ensure_postgres_extensions()
    init_database()
    initialize_langsmith()
    initialize_mcp()

    try:
        from app.services.rag.vector_store import ensure_vector_store_ready

        ensure_vector_store_ready(subject_id=DEFAULT_SUBJECT_ID)
        logger.info("✅ Platform PGVector gateway ready")
    except Exception as exc:
        logger.warning(f"⚠️ Platform PGVector gateway initialization skipped: {exc}")

    logger.info(f"✅ Platform sidecar ready, database={current_database_backend()}")
    try:
        yield
    finally:
        logger.info("👋 LangGraph Platform sidecar stopped")


app = FastAPI(
    title="Learning Assistant LangGraph Platform Sidecar",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "learning-assistant-langgraph"}


__all__ = ["app"]
