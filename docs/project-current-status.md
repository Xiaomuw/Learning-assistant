# 学习助手项目当前状态

> 更新日期：2026-05-12
> 目标读者：项目维护者、接手开发同学、协作 AI / Agent  
> 当前事实源：`backend/app/*`、`frontend/app/*`、`frontend/lib/api.ts`、`backend/langgraph.json`

## 1. 一句话说明

这是一个移动端 H5 学习助手：用户围绕 notebook 构建知识库，通过 RAG 问答、选择题练习和知识点掌握度持续学习。

当前正式栈：

- 后端：FastAPI + LangGraph + LangChain
- 前端：Next.js 14 App Router
- 数据库：PostgreSQL
- 向量库：PGVector
- 模型：DeepSeek / OpenAI-compatible chat provider，embedding 独立使用当前配置的 Google 或 OpenAI-compatible provider

产品语义叫 **notebook / 笔记本**。后端 wire / DB 里仍有 `subject_id`，这是兼容字段，不是新的产品语义。

## 2. 已落地能力

### 账号与鉴权

- 邮箱验证码注册、登录、refresh、logout、修改密码。
- JWT access / refresh 双令牌，使用 `HttpOnly Cookie`。
- 注册发码走 SMTP；SMTP 缺失时接口明确失败，不假装发信。
- `default_user` 只代表历史/开发兼容数据，不再作为正式运行用户。

### 前端页面

- `/login`
- `/register`
- `/chat`
- `/practice`
- `/dashboard`
- `/profile`
- `/help`

页面和组件层使用 `Notebook / notebookId`，`subject_id` 只留在 API wire 兼容边界。

### Notebook、RAG 与向量库

- PDF、URL、自动章节、题库内容都可进入 notebook 知识库。
- 每个 notebook 对应 PGVector collection，默认命名为 `learning_<subject_id>`。
- 入库 metadata 统一包含 `subject_id`、`doc_type`、`source_id`、`knowledge_point`、`chunk_index` 等信息。
- RAG 正式入口是 `backend/app/services/rag/`，包含 loader、splitter、embeddings、vector_store、retriever、rag_service。
- Notebook 知识库 gateway 是 `backend/app/services/notebook_knowledge_base.py`。
- 知识库状态接口：`GET /api/notebooks/{subject_id}/knowledge/status`。

### 主问答与 LangGraph

问题类型包括：

- `concept`
- `problem`
- `review`
- `practice`
- `meta`
- `smalltalk`
- `mcq_problem`

当前正式图名是 `learning_assistant`，生产入口为 `LearningOrchestratorGraph`，核心拓扑为：

```text
LearningOrchestratorGraph -> QAGraph / QuestionGenerationGraph / MasteryEvaluationGraph -> response_composer
```

主问答链路覆盖 `concept / problem / review`：Orchestrator 先做请求守卫、上下文加载和意图路由，再调用 QAGraph。QAGraph 负责 evidence 判断、工具 fallback、QA runtime 调用和 `LearningEvent` 产出。出题和掌握度分别由 `QuestionGenerationGraph` 与 `MasteryEvaluationGraph` 处理。

### 工具、MCP 与 LangSmith

- 工具能力：
  - 正式 capability 层在 `backend/app/services/tooling/`
  - 业务 Graph 只请求 `ToolCapability`，不能直接 import Tavily provider
  - 当前主能力包括 `notebook_retrieve`、`web_search`、`web_extract`
  - 会话摘要、学习画像、推荐题等旧内部工具保留在 QA runtime adapter 内部
- MCP V1：
  - 仅支持 HTTP MCP
  - 仅接网页搜索 / 网页读取
  - 默认关闭，fail-open
  - 不发送完整 notebook 正文、长期记忆或完整会话摘要
- LangSmith：
  - 可选开启
  - 主要覆盖主问答链路
  - 配置缺失或服务异常时不阻断业务

### 练习、题库与掌握度

- 练习题统一为 4 选 1 单选题。
- 题目来源：本地题库优先，不足时 AI 补题，AI 超时则 fallback 补足请求题数。
- 出题请求由 `QuestionGenerationGraph` 处理，刷题页可通过 `POST /api/practice/packs` 基于当前知识点继续补题。
- 做题提交仍兼容写入 `practice_attempts`，并通过 finalizer / repository adapter 转成 graph-era attempt 与学习事件。
- 掌握度由 `MasteryEvaluationGraph` 消费 `LearningEvent / attempts` 并写入 `mastery_snapshots`；旧 `user_knowledge_stats` 只作为历史兼容读取。
- Dashboard 仍通过 `GET /api/users/{user_id}/knowledge/mastery` 获取掌握度视图。

## 3. 后端结构

```text
backend/app/
├── interfaces/      # HTTP 路由、鉴权、SSE、请求/响应 DTO
├── application/     # auth / chat / notebooks / ingest / model_config / practice / user_data
├── orchestration/   # LangGraph enterprise graphs / platform
├── domains/         # qa / memory / practice / mastery
├── services/        # rag / tooling / notebook_knowledge_base / runtime_models
├── infrastructure/  # db / llm / auth / ingest / mcp / config
└── shared/          # AgentState、内部契约、model profile 等共享 schema
```

维护原则：

- `interfaces/*` 是唯一 HTTP 翻译层。
- `application/*` 编排 use case，不直接抛 `HTTPException`。
- `orchestration/*` 只管 LangGraph 图和 runner。
- `domains/*` 放 QA、memory、practice、mastery 业务规则。
- `services/*` 放跨领域服务和 gateway。
- `infrastructure/*` 只连外部世界。
- 新代码不要恢复旧顶层后端目录或 deprecated façade。

## 4. 前端结构

```text
frontend/
├── app/             # Next App Router 页面
├── components/      # H5 UI 组件
├── lib/api.ts       # 唯一 API wire 兼容层
├── lib/learning-store.ts
└── middleware.ts    # 路由守卫
```

维护原则：

- 页面和组件使用 notebook-first 命名。
- `lib/api.ts` 负责把 `/api/subjects`、`subject_id` 归一化为前端 Notebook 类型。
- `lib/learning-store.ts` 负责旧本地 key 读取兼容，新写入使用 notebook-first。
- `AuthProvider` 是当前用户事实来源。

## 5. 数据库事实源

当前主要表：

- `users`
- `auth_refresh_tokens`
- `email_verification_challenges`
- `subjects`
- `user_profiles`
- `user_memories`
- `chat_sessions`
- `question_bank_items`
- `practice_question`
- `practice_attempts`
- `practice_attempt_finalization_jobs`
- `app_settings`
- `kb_subject`
- `kb_chapter`
- `kb_topic`
- `kb_concept`
- `kb_chunk`
- `wechat_mini_identities`
- `graph_runs`
- `node_runs`
- `tool_runs`
- `learning_events`
- `attempts`
- `mastery_snapshots`
- `question_items`
- `concepts`

`user_knowledge_stats` 仍存在于数据库中，但当前 graph-era mastery 事实源是 `mastery_snapshots`；旧表用于兼容读取和历史 backfill。

当前正式运行时不支持 MySQL / SQLite 作为主数据库；它们只在历史迁移或历史文档语境中出现。Chroma 也只作为历史迁移来源，当前向量运行时是 PGVector。

## 6. 外部依赖与开关

- `DATABASE_URL`：启动级必需，必须是 PostgreSQL DSN。
- `TEST_DATABASE_URL`：真实 PostgreSQL 集成测试专用，运行 `make test-backend-postgres` 时必须显式提供。
- `JWT_SECRET_KEY`：启动级必需，不能是占位值。
- `MODEL_ACCESS_KEY` / `OPENAI_API_KEY`：主问答和 embedding 能力需要。
- `SMTP_*`：注册验证码能力需要。
- `LANGSMITH_*`：可选观测。
- `MCP_*`：可选外部工具增强。

真实密钥只放本机 `.env`，不要写入 docs。

## 7. 当前边界

- 不做 OCR / 图片识题。
- MCP V1 不支持 stdio MCP。
- MCP V1 不接数据库、浏览器自动化、文件系统类 MCP。
- 主问答 runtime 只覆盖 `concept / problem / review`。
- `subject_id` wire/db 兼容命名暂不物理迁移。
- 测试数据使用 `codex-test-*` 前缀，不默认清理用户已有数据。

## 8. 推荐阅读顺序

1. [docs/README.md](README.md)
2. [docs/ai-handoff.md](ai-handoff.md)
3. [docs/backend-map.md](backend-map.md)
4. [docs/frontend-map.md](frontend-map.md)
5. [docs/feature-flows.md](feature-flows.md)
6. [docs/langgraph-overview.md](langgraph-overview.md)
7. [docs/database-design.md](database-design.md)

## 9. 最低自检命令

推荐从 repo root 使用统一入口：

```bash
make test-backend
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/test_db make test-backend-postgres
make test-graphs
make eval-graphs
make smoke-backend
```

后端验收分层：

- `/health` 是进程存活检查，只说明 HTTP 进程有响应。
- `scripts/check_environment.py` 是配置与环境检查，不代表认证态 API、数据库写入或 runtime readiness 已通过。
- `make test-backend-postgres` 覆盖真实 PostgreSQL repository/auth/import 等关键集成测试；目标库会被创建临时 schema 并清理。
- `make smoke-backend` 需要后端服务已经启动，默认创建临时用户、登录、访问 `/api/auth/me`、`/api/subjects`、`/api/users/{id}/learning-center`、`/api/users/{id}/practice/recommendations`，最后清理临时账号；它会写入当前 runtime 数据库。
- `make eval-graphs` 仍是本地 deterministic graph smoke eval；LangSmith remote dataset/evaluator 只有在显式运行 remote eval 命令后才能作为通过结论。

如果当前目录已经是 `backend/`：

```bash
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests -t .
```

```bash
cd frontend
npm run lint
npm run build
```
