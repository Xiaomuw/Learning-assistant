"""
学习助手后端正式入口
====================
职责：
  1. 加载环境变量
  2. 初始化 FastAPI 应用
  3. 配置基础中间件
  4. 挂载 interfaces 层路由
  5. 启动基础设施初始化流程
"""

import asyncio
from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

load_dotenv()

from app.infrastructure.config.validation import (  # noqa: E402
    collect_environment_warnings,
    get_cors_allow_origins,
    validate_startup_environment,
)
from app.infrastructure.db.readiness import assert_database_readiness  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402
from app.interfaces.api.chat import router as chat_router  # noqa: E402
from app.interfaces.api.model_config import router as model_config_router  # noqa: E402
from app.interfaces.api.practice import router as practice_router  # noqa: E402
from app.interfaces.api.subjects import router as subjects_router  # noqa: E402
from app.interfaces.api.upload import router as upload_router  # noqa: E402
from app.interfaces.api.user_data import router as user_data_router  # noqa: E402
from app.interfaces.auth.router import router as auth_router  # noqa: E402

ensure_model_env_aliases()

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _practice_finalizer_worker_enabled() -> bool:
    return str(os.getenv("ENABLE_PRACTICE_FINALIZER_WORKER", "")).strip().lower() in _TRUE_VALUES


def _practice_finalizer_worker_interval_seconds() -> float:
    raw = str(os.getenv("PRACTICE_FINALIZER_WORKER_INTERVAL_SECONDS", "30")).strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 30.0


def _practice_finalizer_worker_limit() -> int:
    raw = str(os.getenv("PRACTICE_FINALIZER_WORKER_LIMIT", "20")).strip()
    try:
        return max(1, min(int(raw), 100))
    except ValueError:
        return 20


async def _practice_finalizer_worker() -> None:
    from app.application.practice.service import run_due_practice_attempt_finalization_jobs

    interval = _practice_finalizer_worker_interval_seconds()
    limit = _practice_finalizer_worker_limit()
    logger.info("✅ Practice finalizer worker 已启动 | interval={}s | limit={}", interval, limit)
    try:
        while True:
            try:
                summary = await asyncio.to_thread(run_due_practice_attempt_finalization_jobs, limit=limit)
                if summary.get("due"):
                    logger.info(
                        "✅ Practice finalizer worker 本轮完成 | due={} | claimed={} | completed={} | failed={} | dead={} | skipped={}",
                        summary.get("due", 0),
                        summary.get("claimed", 0),
                        summary.get("completed", 0),
                        summary.get("failed", 0),
                        summary.get("dead", 0),
                        summary.get("skipped", 0),
                    )
            except Exception as exc:  # pragma: no cover - 后台恢复循环必须 fail-open
                logger.exception("Practice finalizer worker 本轮失败: {}", exc.__class__.__name__)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("👋 Practice finalizer worker 已停止")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 学习问答助手后端启动中 ...")

    validate_startup_environment()
    for warning in collect_environment_warnings():
        logger.warning(f"⚠️ {warning}")

    db_report = assert_database_readiness()
    logger.info(
        "✅ 数据库只读 readiness 通过 | "
        f"backend={db_report.database_backend} | "
        f"alembic={','.join(db_report.alembic_current_revisions)} | "
        f"tables={db_report.required_table_count} | "
        f"indexes={db_report.required_index_count} | "
        f"vector_extension={db_report.vector_extension_ready}"
    )

    from app.orchestration.graphs.orchestrator.graph import build_graph

    build_graph().compile()
    logger.info("✅ LearningOrchestratorGraph 已编译")

    finalizer_worker_task = None
    if _practice_finalizer_worker_enabled():
        finalizer_worker_task = asyncio.create_task(_practice_finalizer_worker())

    logger.info("🚀 启动完成，服务就绪")
    try:
        yield
    finally:
        if finalizer_worker_task is not None:
            finalizer_worker_task.cancel()
            try:
                await finalizer_worker_task
            except asyncio.CancelledError:
                pass
        logger.info("👋 学习问答助手后端已关闭")


app = FastAPI(
    title="多 Agent 学习问答助手",
    description="基于 LangGraph 多 Agent 架构的智能学习辅导系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api", tags=["Auth"])
app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(upload_router, prefix="/api", tags=["Upload"])
app.include_router(model_config_router, prefix="/api", tags=["Model Config"])
app.include_router(practice_router, prefix="/api", tags=["Practice"])
app.include_router(subjects_router, prefix="/api", tags=["Subjects"])
app.include_router(user_data_router, prefix="/api", tags=["User Data"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "learning-assistant"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
    )
