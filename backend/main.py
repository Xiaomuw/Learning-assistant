"""
多 Agent 学习问答助手 — FastAPI 入口
====================================
职责：
  1. 加载环境变量
  2. 初始化 FastAPI 应用
  3. 挂载所有路由
  4. 配置 CORS / 全局异常处理
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from db.database import current_database_backend
from db.repositories import init_database, list_subjects
from tools.model_provider import ensure_model_env_aliases

# ---------- 加载 .env ----------
load_dotenv()
ensure_model_env_aliases()

# ---------- 路由导入 ----------
from api.chat import router as chat_router      # noqa: E402
from api.upload import router as upload_router    # noqa: E402
from api.model_config import router as model_config_router  # noqa: E402
from api.subjects import router as subjects_router  # noqa: E402
from api.user_data import router as user_data_router  # noqa: E402


# ---------- Lifespan（应用启动/关闭钩子） ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ---- startup ----
    logger.info("🚀 学习问答助手后端启动中 ...")

    init_database()
    logger.info(f"✅ 数据库就绪，当前后端: {current_database_backend()}")

    subjects = list_subjects()
    logger.info(f"✅ 学科列表就绪，共 {len(subjects)} 个学科")

    # 预初始化 Chroma 客户端和 Collection
    from tools.retriever import get_chroma_client, get_collection
    try:
        client = get_chroma_client()
        collection = get_collection(subject_id="general")
        logger.info(f"✅ Chroma 就绪，通用知识文档数: {collection.count()}")
    except Exception as e:
        logger.warning(f"⚠️ Chroma 初始化失败（可稍后重试）: {e}")

    # 预编译 LangGraph 工作流
    from graph.workflow import compiled_graph  # noqa: F401
    logger.info("✅ LangGraph 工作流已编译")

    logger.info("🚀 启动完成，服务就绪")
    yield
    # ---- shutdown ----
    logger.info("👋 学习问答助手后端已关闭")


# ---------- 创建 FastAPI 实例 ----------
app = FastAPI(
    title="多 Agent 学习问答助手",
    description="基于 LangGraph 多 Agent 架构的智能学习辅导系统",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # TODO: 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 挂载路由 ----------
app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(upload_router, prefix="/api", tags=["Upload"])
app.include_router(model_config_router, prefix="/api", tags=["Model Config"])
app.include_router(subjects_router, prefix="/api", tags=["Subjects"])
app.include_router(user_data_router, prefix="/api", tags=["User Data"])


# ---------- 健康检查 ----------
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "learning-assistant"}


# ---------- 启动入口 ----------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
