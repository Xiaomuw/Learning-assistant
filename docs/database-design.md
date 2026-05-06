# 学习助手数据库设计文档

> 更新日期：2026-04-28  
> 设计口径：**PostgreSQL 单栈持久化**

## 1. 当前数据库策略

当前项目已经统一到一套 PostgreSQL 存储架构：

- **业务事实表**：SQLAlchemy + PostgreSQL
- **向量检索**：PGVector
- **LangGraph 线程持久化**：PostgresSaver
- **运行时约束**：不再支持 MySQL / SQLite 回退

产品语义仍然使用 **notebook / 笔记本**，内部字段保留 `subject / subject_id` 作为兼容实现。

## 2. 业务表总览

| 表名 | 主用途 |
| --- | --- |
| `subjects` | 笔记本 / notebook 容器 |
| `users` | 本地账号 |
| `user_profiles` | 用户昵称与 Agent 风格 |
| `user_memories` | 长期学习画像 |
| `user_knowledge_stats` | 知识点掌握度统计 |
| `auth_refresh_tokens` | Refresh Token 会话 |
| `email_verification_challenges` | 注册邮箱验证码挑战 |
| `chat_sessions` | UI 历史会话、最近题包、会话摘要 |
| `question_bank_items` | 本地题库 / 真题镜像 |
| `practice_attempts` | 做题记录 |
| `app_settings` | 全局配置（如当前模型） |

## 3. 字段设计特点

- JSON 结构统一使用 **PostgreSQL `JSONB`**
- 当前业务表仍然**没有显式外键约束**
- `chat_sessions` 继续作为前端历史回放的**唯一产品读模型**
- `user_knowledge_stats` 是知识点掌握度事实来源
- `user_memories` 保留为长期学习画像与兼容聚合视图

## 4. 向量存储设计

- 运行时向量库为 **PGVector**
- 每个笔记本隔离到一个 collection，命名默认是 `learning_<subject_id>`
- 默认通用 collection 为 `learning_docs`
- 入库正式入口统一在 [backend/app/services/rag/rag_service.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/services/rag/rag_service.py)，底层 PGVector 操作在 [backend/app/services/rag/vector_store.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/app/services/rag/vector_store.py)

## 5. LangGraph 持久化设计

- LangGraph 工作流由 `session_id` 作为 `thread_id`
- Checkpointer 使用 `PostgresSaver`
- 首次启动时执行 `checkpointer.setup()`
- 线程执行态写入 Postgres，但**不会替代** `chat_sessions` 作为产品历史来源

## 6. 启动初始化

应用启动顺序：

1. 加载 `DATABASE_URL`
2. 执行 `CREATE EXTENSION IF NOT EXISTS vector`
3. 初始化 SQLAlchemy 业务表
4. 初始化 PGVector collection
5. 初始化 LangGraph PostgresSaver

## 7. 迁移策略

一次性迁移脚本位于 [backend/scripts](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/scripts)：

- [migrate_structured_data_to_postgres.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/scripts/migrate_structured_data_to_postgres.py)
  - 支持 MySQL / SQLite / PostgreSQL 作为源库
  - 保留主键、时间戳、JSON 结构
- [migrate_chroma_to_pgvector.py](/Users/xiaomu/Desktop/Python/Code/learning-assistant/backend/scripts/migrate_chroma_to_pgvector.py)
  - 支持本地目录或远程 Chroma
  - 优先直接复用旧 embedding
  - 缺失时回退重算 embedding

## 8. 推荐环境变量

```env
DATABASE_URL=postgresql+psycopg://learning_user:password@127.0.0.1:5432/learning_assistant
LANGGRAPH_POSTGRES_URL=postgresql://learning_user:password@127.0.0.1:5432/learning_assistant
PGVECTOR_COLLECTION_PREFIX=learning
PGVECTOR_DEFAULT_COLLECTION=learning_docs
```
