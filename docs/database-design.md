# 学习助手数据库设计文档

> 更新日期：2026-05-12  
> 设计口径：**PostgreSQL 单栈持久化**

## 1. 当前数据库策略

当前项目已经统一到一套 PostgreSQL 存储架构：

- **业务事实表**：SQLAlchemy + PostgreSQL
- **向量检索**：PGVector
- **Graph-era 事实表**：Alembic migration + repository Protocol
- **运行时约束**：不再支持 MySQL / SQLite 回退

产品语义仍然使用 **notebook / 笔记本**，内部字段保留 `subject / subject_id` 作为兼容实现。

生产 schema 以 `backend/alembic/versions/*` 为准；`Base.metadata.create_all()` 只保留本地 bootstrap 兼容，不能替代 migration。

## 2. 业务表总览

| 表名 | 主用途 |
| --- | --- |
| `subjects` | 笔记本 / notebook 容器 |
| `users` | 本地账号 |
| `user_profiles` | 用户昵称与 Agent 风格 |
| `user_memories` | 长期学习画像 |
| `auth_refresh_tokens` | Refresh Token 会话 |
| `wechat_mini_identities` | 微信小程序身份绑定 |
| `email_verification_challenges` | 注册邮箱验证码挑战 |
| `chat_sessions` | UI 历史会话、最近题包、会话摘要 |
| `kb_subject / kb_chapter / kb_topic / kb_concept / kb_chunk` | 知识体系、章节、主题、概念、chunk 结构化索引 |
| `question_bank_items` | 本地题库 / 真题镜像 |
| `practice_question` | 导入或生成后的练习题记录 |
| `practice_attempts` | 做题记录 |
| `practice_attempt_finalization_jobs` | 做题提交到 graph-era facts 的幂等 finalizer 任务 |
| `app_settings` | 全局配置（如当前模型） |
| `graph_runs / node_runs / tool_runs` | Graph、节点、工具运行审计事实 |
| `learning_events` | 跨 Graph 学习事件 |
| `attempts` | graph-era 答题事实 |
| `mastery_snapshots` | graph-era 掌握度快照事实 |
| `question_items` | QuestionGenerationGraph 题目事实 |
| `concepts` | graph-era 概念事实 |

`user_knowledge_stats` 仍在当前 ORM 中保留，用于历史兼容读取和 backfill，不再作为 graph-era mastery 的唯一事实来源。

## 3. 字段设计特点

- JSON 结构统一使用 **PostgreSQL `JSONB`**
- 核心账号、KB、graph-era facts、practice finalizer 等约束由 Alembic 逐步管理
- `chat_sessions` 继续作为前端历史回放的**唯一产品读模型**
- `mastery_snapshots` 是当前 graph-era 掌握度事实来源
- `user_memories` 保留为长期学习画像与兼容聚合视图

## 4. 向量存储设计

- 运行时向量库为 **PGVector**
- 每个笔记本隔离到一个 collection，命名默认是 `learning_<subject_id>`
- 默认通用 collection 为 `learning_docs`
- 入库正式入口统一在 [backend/app/services/rag/rag_service.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/services/rag/rag_service.py)，底层 PGVector 操作在 [backend/app/services/rag/vector_store.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/services/rag/vector_store.py)

## 5. LangGraph 与 graph-era 事实

- LangGraph 工作流由 `session_id` 作为 `thread_id`
- FastAPI 当前本地运行路径直接编译 `LearningOrchestratorGraph`
- 长期业务事实不能只放在 checkpoint 中，必须通过 repository 写入 graph-era facts
- `chat_sessions` 仍是前端历史页的产品读模型，不被 graph facts 替代
- LangGraph Platform sidecar 的运行时持久化由 Platform Agent Server 负责，和 FastAPI 产品历史表分离

## 6. 启动初始化

应用启动顺序：

1. 加载 `DATABASE_URL`
2. 执行 `CREATE EXTENSION IF NOT EXISTS vector`
3. 通过 Alembic 管理生产 schema；本地 bootstrap 可初始化 SQLAlchemy 表
4. 初始化 PGVector collection
5. 编译 Orchestrator / 子 Graph，并通过 repository 写入 graph-era facts

## 7. 迁移策略

一次性迁移脚本位于 [backend/scripts](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/scripts)：

- [migrate_structured_data_to_postgres.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/scripts/migrate_structured_data_to_postgres.py)
  - 支持 MySQL / SQLite / PostgreSQL 作为源库
  - 保留主键、时间戳、JSON 结构
- Chroma 只作为历史迁移来源保留在文档背景中；当前项目内不再维护 Chroma 到 PGVector 的迁移脚本。

## 8. 推荐环境变量

```env
DATABASE_URL=postgresql+psycopg://learning_user:password@127.0.0.1:5432/learning_assistant
PGVECTOR_COLLECTION_PREFIX=learning
PGVECTOR_DEFAULT_COLLECTION=learning_docs
```
