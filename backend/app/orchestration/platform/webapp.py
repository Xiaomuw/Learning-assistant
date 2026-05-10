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
from app.infrastructure.db.readiness import assert_database_readiness  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402


ensure_model_env_aliases()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 LangGraph Platform sidecar starting ...")

    validate_startup_environment()
    for warning in collect_environment_warnings():
        logger.warning(f"⚠️ {warning}")

    db_report = assert_database_readiness()
    logger.info(
        "✅ Platform database readiness passed | "
        f"backend={db_report.database_backend} | "
        f"alembic={','.join(db_report.alembic_current_revisions)} | "
        f"tables={db_report.required_table_count} | "
        f"indexes={db_report.required_index_count} | "
        f"vector_extension={db_report.vector_extension_ready}"
    )

    from app.orchestration.graphs.orchestrator.graph import build_graph

    build_graph().compile()
    logger.info("✅ Platform LearningOrchestratorGraph compiled")

    logger.info("✅ Platform sidecar ready")
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
