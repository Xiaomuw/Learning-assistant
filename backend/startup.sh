#!/usr/bin/env bash
# ============================================================
# 后端启动脚本
# ============================================================
set -e

echo "📦 安装 Python 依赖..."
pip install --no-cache-dir -r requirements.txt

echo "📂 创建数据目录..."
mkdir -p data/memory

LOG_LEVEL_LOWER=$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')

echo "🚀 启动 FastAPI 服务..."
exec uvicorn main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    --reload \
    --log-level "${LOG_LEVEL_LOWER}"
