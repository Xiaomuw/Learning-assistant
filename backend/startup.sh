#!/usr/bin/env bash
# ============================================================
# 后端启动脚本
# ============================================================
set -e

echo "📂 创建存储目录..."
mkdir -p storage/data/memory

echo "🔍 检查环境配置..."
python scripts/check_environment.py

if [ "${RUN_ALEMBIC_UPGRADE:-true}" = "true" ]; then
    echo "🧱 执行数据库迁移..."
    python scripts/run_migrations_with_diagnostics.py
else
    echo "⏭️  跳过数据库迁移：RUN_ALEMBIC_UPGRADE=${RUN_ALEMBIC_UPGRADE}"
fi

if [ "${RUN_BOOTSTRAP_APP_DATA:-true}" = "true" ]; then
    echo "🌱 补齐默认应用数据..."
    python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
else
    echo "⏭️  跳过默认应用数据 bootstrap：RUN_BOOTSTRAP_APP_DATA=${RUN_BOOTSTRAP_APP_DATA}"
fi

if [ "${RUN_BUILTIN_NOTEBOOK_SEED:-false}" = "true" ]; then
    echo "🌱 补齐内置 notebook 知识库与题库..."
    SEED_ARGS=()
    if [ -n "${BUILTIN_NOTEBOOK_SEED_SUBJECTS:-}" ]; then
        SEED_ARGS+=("--subjects" "${BUILTIN_NOTEBOOK_SEED_SUBJECTS}")
    fi
    if [ -n "${BUILTIN_NOTEBOOK_SEED_CURRICULUM:-}" ]; then
        SEED_ARGS+=("--curriculum" "${BUILTIN_NOTEBOOK_SEED_CURRICULUM}")
    fi
    if [ "${BUILTIN_NOTEBOOK_SEED_WITH_QUESTIONS:-true}" = "true" ]; then
        SEED_ARGS+=("--with-questions")
    fi
    if [ "${BUILTIN_NOTEBOOK_SEED_FORCE:-false}" = "true" ]; then
        SEED_ARGS+=("--force")
    fi
    python scripts/seed_builtin_notebook_vectors.py "${SEED_ARGS[@]}"
else
    echo "⏭️  跳过内置 notebook seed：RUN_BUILTIN_NOTEBOOK_SEED=${RUN_BUILTIN_NOTEBOOK_SEED:-false}"
fi

echo "🔌 检查 MCP 外部工具..."
python scripts/check_mcp_runtime.py

LOG_LEVEL_LOWER=$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')

echo "🚀 启动 FastAPI 服务..."
exec python -m uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    --log-level "${LOG_LEVEL_LOWER}"
