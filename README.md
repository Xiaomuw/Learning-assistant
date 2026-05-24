# 学习助手

一个面向移动端 H5 与微信小程序的 AI 学习助手。当前正式栈是 **FastAPI + LangGraph + LangChain + PostgreSQL/PGVector + Next.js + Taro**。

用户围绕 **notebook / 笔记本** 组织资料和练习：上传 PDF/URL 或使用内置题库后，系统通过 RAG 问答、选择题练习、学习事件和掌握度快照持续辅助学习。后端 wire、数据库和部分历史字段仍保留 `subject_id` 兼容命名；产品和前端语义优先使用 notebook。

> 当前正式运行时只支持 **PostgreSQL + PGVector**。MySQL / SQLite / Chroma 只作为历史迁移语境保留，不是当前主运行方案。

## 当前能力

- 账号与鉴权：邮箱验证码注册、登录、refresh、logout、修改密码；Web 端使用 HttpOnly Cookie，小程序端使用 Bearer token。
- Notebook 知识库：支持 PDF、URL、自动章节、题库内容入库，向量检索落在 PGVector。
- 主问答：`LearningOrchestratorGraph` 做决策边界和子图路由，`QAGraph` 负责解释、教学、证据判断、RAG、工具 fallback 与学习事件。
- 练习与掌握度：`QuestionGenerationGraph` 生成 4 选 1 单选题，本地题库优先、AI 补题兜底；`MasteryEvaluationGraph` 消费 attempts / learning events 并写入 `mastery_snapshots`。
- 外部增强：联网搜索通过 `web_search` capability 受策略控制，可选 Tavily / HTTP MCP；LangSmith 可选观测，配置缺失时主业务 fail-open。
- 多端交付：Next.js H5 使用 SSE 流式问答；微信小程序支持 chunked SSE，云托管不可流式时自动降级到同步接口和后台 job 轮询。

## 核心架构

```mermaid
flowchart TD
    C["Next.js H5 / Taro 微信小程序"] --> A["FastAPI /api"]
    A --> S["application/chat service"]
    S --> O["LearningOrchestratorGraph"]
    O --> D{"Decision Boundary Router"}
    D -->|"simple_fact / meta_tool_usage"| R["Direct Response"]
    D -->|"practice_generation"| QG["QuestionGenerationGraph"]
    D -->|"concept / problem / review / notebook QA"| QA["QAGraph"]
    D -->|"mastery"| M["MasteryEvaluationGraph"]
    QA --> T["Tooling Capability Policy"]
    T --> RAG["Notebook RAG / PGVector"]
    T --> WEB["web_search / web_extract"]
    QG --> E["question_items + LearningEvent"]
    QA --> LE["LearningEvent"]
    M --> MS["mastery_snapshots"]
    O --> OUT["response_composer"]
```

维护边界：

- `LearningOrchestratorGraph` 只做请求守卫、上下文加载、意图路由、子图调用、响应组合和审计。
- `QAGraph` 只做问答、证据判断、工具 fallback、grounding 和 learning events，不写 mastery / question / attempt。
- `QuestionGenerationGraph` 只做出题、质量检查、修复、去重、题目持久化和生成事件。
- `MasteryEvaluationGraph` 是掌握度写入边界，负责更新 `mastery_snapshots`。

## 决策边界规则

- 简单事实和确定性小计算，例如 `1+1等于几`，走 `simple_fact` 直接回答，不进入 RAG。
- 练习/出题请求走 `practice_generation`，优先进入 `QuestionGenerationGraph`，不绕到普通 QA。
- 工具轨迹/是否联网等元问题走 `meta_tool_usage`，只读取上一轮安全化后的 tool trace；tool trace 默认不注入普通 QA 上下文。
- 实时、新鲜度、官网来源类问题走 `realtime_or_fresh`；只有本轮 `allow_web=true` 且策略允许时才可进入 web capability。
- `source_policy=notebook_only` 时只能使用 notebook evidence；内部证据不足要明确不足，不能编造，也不能越权联网。
- Web 搜索结果进入回答前必须经过外部证据判断；`answer_repair` 和出题 repair 都有最大次数，不能无限重试。

## 移动同步交付

微信小程序优先尝试 `/api/chat` SSE；当运行环境不支持 chunked 或使用云托管容器调用时，会走同步兜底：

- `POST /api/chat/sync`：同步问答入口。能在 inline budget 内完成时直接返回 `status=completed`。
- 超过预算时返回 `status=pending`、`job_id`、`request_id`、`retry_after_ms`。
- `GET /api/chat/jobs/{job_id}`：查询后台聊天任务结果。
- `POST /api/chat/jobs/{job_id}/poll`：小程序云托管轮询入口。
- 后台任务状态持久化在 `chat_async_jobs`，不是只放进程内存。
- `client_request_id` / `X-Client-Request-ID` 用于同一客户端请求幂等；重复请求会复用同一个 job。
- job 带服务端过期时间，过期后返回结构化 `chat_job_expired` 错误。

相关实现入口：`backend/app/interfaces/api/chat.py`、`backend/app/infrastructure/db/repositories/chat_jobs.py`、`frontend-weapp/src/services/chat-stream.ts`。

## 目录速览

```text
backend/
  app/
    interfaces/      # HTTP 路由、鉴权、SSE、请求/响应 DTO
    application/     # auth / chat / notebooks / ingest / practice 等用例编排
    orchestration/   # LangGraph orchestrator / QA / question generation / mastery
    domains/         # qa / memory / practice / mastery 领域逻辑
    services/        # rag / tooling / notebook_knowledge_base / runtime_models
    infrastructure/  # db / llm / auth / ingest / mcp / config
    shared/          # 共享 schema 和契约
frontend/            # Next.js 14 App Router H5
frontend-weapp/      # Taro 4 + React 微信小程序
data/                # 内置 408 题库与导入数据
docs/                # 架构、接口、数据库、部署和交接文档
```

## 本地启动

### 1. 后端

后端默认端口 `8000`。启动前需要准备 PostgreSQL + PGVector，并把真实配置写入 `backend/.env`。

```bash
cd backend
cp .env.example .env
python -m venv .venv313
source .venv313/bin/activate
pip install -r requirements.txt
python scripts/check_environment.py
python scripts/run_migrations_with_diagnostics.py
python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
python -m app.main
```

Windows PowerShell 可把激活命令换成：

```powershell
.\.venv313\Scripts\Activate.ps1
```

### 2. Next.js H5

前端默认端口 `3000`。

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3000
```

### 3. 微信小程序

```bash
cd frontend-weapp
npm install
npm run typecheck
npm run lint
npm run build:weapp
```

微信开发者工具打开 `frontend-weapp/`，`miniprogramRoot` 指向 `dist/`。本地默认 API 是 `http://127.0.0.1:8000/api`；真机预览必须配置 HTTPS 后端域名。

### 4. Docker Compose

开发/稳定本地模式：

```bash
cp backend/.env.example backend/.env
docker compose up -d --build
```

默认映射：

- PostgreSQL: `127.0.0.1:5433`
- Backend: `127.0.0.1:8002`
- Frontend: `127.0.0.1:3001`

生产部署参考 [docs/DEPLOY.md](docs/DEPLOY.md) 与 `docker-compose.prod.yml`。

## 环境变量

真实密钥只写入本机 `.env`，不要提交到仓库。常用配置见 [backend/.env.example](backend/.env.example) 和根目录 [.env.example](.env.example)。

关键变量：

- `DATABASE_URL`：必填，必须是 PostgreSQL DSN。
- `LANGGRAPH_POSTGRES_URL`：LangGraph checkpoint / platform 相关 PostgreSQL DSN。
- `JWT_SECRET_KEY`：必填，至少 32 位随机密钥；生产不能使用占位值。
- `MODEL_ACCESS_KEY` / `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`：OpenAI-compatible chat provider。
- `OPENAI_EMBEDDING_*` / `EMBEDDING_PROVIDER`：embedding provider。
- `SMTP_*`：注册验证码发信；未配置时发码接口会明确失败。
- `WECHAT_MINI_APP_ID` / `WECHAT_MINI_APP_SECRET`：小程序登录。
- `LANGSMITH_*`：可选观测。
- `MCP_*`、`TAVILY_API_KEY`：可选联网搜索 provider。
- `CHAT_SYNC_INLINE_BUDGET_SECONDS`、`CHAT_SYNC_POLL_RETRY_AFTER_MS`、`CHAT_SYNC_JOB_TTL_SECONDS`：移动同步交付预算、轮询间隔和 job 过期时间。

生产环境还需要注意：

- `APP_ENV=production` 时 `CORS_ALLOW_ORIGINS` 不能是 `*`。
- `APP_ENV=production` 时必须设置 `AUTH_COOKIE_SECURE=true`。
- 小程序生产登录必须配置真实 WeChat appid/secret。

## API 入口概览

- Auth：`/api/auth/register/send-code`、`/api/auth/register/complete`、`/api/auth/login`、`/api/auth/refresh`、`/api/auth/logout`、`/api/auth/me`、`/api/auth/wechat-mini/*`
- Chat：`POST /api/chat`、`POST /api/chat/sync`、`GET /api/chat/jobs/{job_id}`、`POST /api/chat/jobs/{job_id}/poll`
- Notebooks：`/api/notebooks` 与兼容别名 `/api/subjects`
- Knowledge ingest：`POST /api/upload`、`POST /api/upload/urls`
- Practice：`GET /api/users/{user_id}/practice/recommendations`、`POST /api/practice/attempts`、`POST /api/practice/packs`
- User data：`/api/users/{user_id}/memory`、`/api/users/{user_id}/knowledge/mastery`、`/api/users/{user_id}/learning-center`、`/api/users/{user_id}/sessions`
- Model settings：`/api/settings/model`、`/api/settings/model/health`、`/api/settings/observability/langsmith/health`

完整接口说明见 [docs/api-reference.md](docs/api-reference.md)。

## 测试与自检

推荐从仓库根目录运行：

```bash
make test-backend
make test-graphs
make eval-graphs
make check-frontend
make check-weapp
git diff --check
```

需要真实 PostgreSQL 集成测试时显式提供测试库：

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/test_db make test-backend-postgres
```

后端分阶段排查：

```bash
cd backend
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests -t .
./.venv313/bin/python scripts/smoke_backend.py --base-url http://127.0.0.1:8000
```

说明：

- `/health` 只证明 FastAPI 进程能响应，不证明数据库、PGVector、认证、模型或 LangGraph runtime 全部就绪。
- `scripts/check_environment.py` 是启动级配置检查，不等于 authenticated runtime smoke。
- `make smoke-backend` 会访问正在运行的后端并写入当前 runtime 数据库中的临时测试用户。

## 推荐阅读顺序

1. [docs/README.md](docs/README.md)：项目文档总索引。
2. [docs/project-current-status.md](docs/project-current-status.md)：当前产品和技术事实源。
3. [docs/ai-handoff.md](docs/ai-handoff.md)：给后续 AI / Agent 的交接卡。
4. [docs/backend-map.md](docs/backend-map.md)：后端目录、聊天主链路、RAG / Tool / LangGraph 入口。
5. [docs/frontend-map.md](docs/frontend-map.md)：Next H5 页面、状态和 API 适配边界。
6. [docs/frontend-weapp-map.md](docs/frontend-weapp-map.md)：微信小程序、流式/同步降级和发布要点。
7. [docs/feature-flows.md](docs/feature-flows.md)：登录、Notebook 入库、RAG、练习、掌握度流程图。
8. [docs/langgraph-overview.md](docs/langgraph-overview.md)：LangGraph 图结构和节点职责。
9. [docs/database-design.md](docs/database-design.md)：PostgreSQL / PGVector / graph-era facts 数据库设计。

## 维护约定

- 新后端代码进入 `backend/app/*`，遵循 `interfaces -> application -> orchestration/domains/services/infrastructure/shared` 分层。
- `interfaces/*` 是唯一 HTTP 翻译层；`application/*` 不直接抛 `HTTPException`。
- Notebook 知识库操作统一走 `backend/app/services/notebook_knowledge_base.py`。
- RAG 正式入口是 `backend/app/services/rag/`。
- 工具执行正式入口是 `backend/app/services/tooling/` capability 层；业务图只请求 capability，不直接依赖 Tavily / MCP provider。
- 当前活动模型选择统一走 `backend/app/services/runtime_models.py`。
- 前端页面和组件使用 `Notebook / notebookId`；`subject_id` 只留在 API wire 兼容边界。
- Learning events、practice finalizer、chat async jobs 都不能只依赖进程内存；移动端轮询必须返回 `retry_after_ms` 并遵守服务端过期。
