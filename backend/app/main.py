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

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

load_dotenv()

from app.infrastructure.config.validation import (  # noqa: E402
    collect_environment_warnings,
    validate_startup_environment,
)
from app.infrastructure.db.database import current_database_backend, ensure_postgres_extensions  # noqa: E402
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: E402
from app.infrastructure.db.repositories.subjects import list_subject_records  # noqa: E402
from app.infrastructure.llm.langsmith import initialize_langsmith  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402
from app.interfaces.api.chat import router as chat_router  # noqa: E402
from app.interfaces.api.model_config import router as model_config_router  # noqa: E402
from app.interfaces.api.practice import router as practice_router  # noqa: E402
from app.interfaces.api.subjects import router as subjects_router  # noqa: E402
from app.interfaces.api.upload import router as upload_router  # noqa: E402
from app.interfaces.api.user_data import router as user_data_router  # noqa: E402
from app.interfaces.auth.router import router as auth_router  # noqa: E402
from app.infrastructure.mcp import initialize_mcp  # noqa: E402
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID  # noqa: E402

ensure_model_env_aliases()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 学习问答助手后端启动中 ...")

    validate_startup_environment()
    for warning in collect_environment_warnings():
        logger.warning(f"⚠️ {warning}")

    ensure_postgres_extensions()
    logger.info("✅ PostgreSQL 扩展就绪（vector）")

    init_database()
    logger.info(f"✅ 数据库就绪，当前后端: {current_database_backend()}")

    initialize_langsmith()
    initialize_mcp()

    subjects = list_subject_records()
    logger.info(f"✅ 学科列表就绪，共 {len(subjects)} 个学科")

    from app.services.rag.vector_store import count_collection_documents, ensure_vector_store_ready

    try:
        ensure_vector_store_ready(subject_id=DEFAULT_SUBJECT_ID)
        doc_count = count_collection_documents(subject_id=DEFAULT_SUBJECT_ID)
        logger.info(f"✅ PGVector 就绪，默认辅助知识库文档数: {doc_count}")
    except Exception as exc:
        logger.warning(f"⚠️ PGVector 初始化失败（可稍后重试）: {exc}")

    from app.orchestration.graphs.orchestrator.graph import build_graph

    build_graph().compile()
    logger.info("✅ LearningOrchestratorGraph 已编译")

    logger.info("🚀 启动完成，服务就绪")
    try:
        yield
    finally:
        logger.info("👋 学习问答助手后端已关闭")


app = FastAPI(
    title="多 Agent 学习问答助手",
    description="基于 LangGraph 多 Agent 架构的智能学习辅导系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
