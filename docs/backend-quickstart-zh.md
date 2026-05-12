# 后端速查（PostgreSQL 版）

## 启动顺序

1. 读取 `.env`
2. 初始化 PostgreSQL `vector` 扩展
3. 初始化 SQLAlchemy 业务表
4. 预热 PGVector collection
5. 编译 `LearningOrchestratorGraph`，Graph 长期事实通过 repository 写入 Alembic 管理表

## 关键入口

- [backend/app/main.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/main.py)
- [backend/app/infrastructure/db/database.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/infrastructure/db/database.py)
- [backend/app/services/rag/rag_service.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/services/rag/rag_service.py)
- [backend/app/orchestration/graphs/orchestrator/graph.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/orchestration/graphs/orchestrator/graph.py)

补充说明：

- [backend/main.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/main.py) 只做启动转发，正式入口是 `app.main:app`
- 旧的 `backend/api`、`backend/agents`、`backend/db` 等顶层兼容目录已经删除；新增代码只走 `backend/app/...`

## 现在的存储口径

- 业务表：PostgreSQL
- 向量库：PGVector
- Graph-era 长期事实：`graph_runs / learning_events / attempts / mastery_snapshots / question_items` 等 Alembic 表
- 不再支持 SQLite 自动回退
- 历史 MySQL 只通过结构化迁移脚本导入；Chroma 仅作为历史背景，不再维护项目内迁移脚本
