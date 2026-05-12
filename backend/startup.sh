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
    python -m alembic upgrade head
fi

LOG_LEVEL_LOWER=$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')

echo "🚀 启动 FastAPI 服务..."
exec python -m uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    --log-level "${LOG_LEVEL_LOWER}"
