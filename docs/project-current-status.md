# 学习助手项目当前状态

> 更新日期：2026-04-28  
> 目标读者：项目维护者、接手开发同学、协作 AI / Agent  
> 当前事实源：`backend/app/*`、`frontend/app/*`、`frontend/lib/api.ts`、`backend/langgraph.json`

## 1. 一句话说明

这是一个移动端 H5 学习助手：用户围绕 notebook 构建知识库，通过 RAG 问答、选择题练习和知识点掌握度持续学习。

当前正式栈：

- 后端：FastAPI + LangGraph + LangChain
- 前端：Next.js 14 App Router
- 数据库：PostgreSQL
- 向量库：PGVector
- 模型：OpenAI-compatible provider，当前本地配置使用 DigitalOcean Model Access

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

当前正式图名是 `learning_assistant`，核心拓扑为：

```text
preflight_node -> router -> 分支节点 -> memory_node / graph_error_node -> finalize_node -> END
```

主问答链路覆盖 `concept / problem / review`：

1. `preflight_node` 做输入规范化、空问题/超长问题/缺失 ID 的图级校验。
2. `router` 分类。
3. `rag_node` 先完成 notebook 检索与质量诊断。
4. `qa_agent_node` 进入 QA runtime，并复用 RAG 上下文生成回答。
5. QA runtime 读取 model profile。
6. QA runtime 执行 preprocess middleware。
7. QA runtime 选择 direct / tool / structured / fallback。
8. QA runtime 执行 postprocess middleware。
9. `memory_node` 更新记忆。
10. `finalize_node` 统一写入 `finalized / final_response_type / route_decision`。

`review` 会额外经过 `quiz_gen` 生成练习题包。

### 工具、MCP 与 LangSmith

- 内部工具：
  - `search_notebook_context`
  - `get_session_summary`
  - `get_user_learning_profile`
  - `recommend_questions`
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
- 做题提交写入 `practice_attempts`。
- 知识点掌握度写入 `user_knowledge_stats`。
- Dashboard 优先展示 `GET /api/users/{user_id}/knowledge/mastery`，失败时 fallback 到旧记忆数据。

## 3. 后端结构

```text
backend/app/
├── interfaces/      # HTTP 路由、鉴权、SSE、请求/响应 DTO
├── application/     # auth / chat / notebooks / ingest / model_config / practice / user_data
├── orchestration/   # LangGraph agents / graph / workflow / platform
├── domains/         # qa / memory / practice / mastery
├── services/        # rag / tools / notebook_knowledge_base / runtime_models
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
- `user_knowledge_stats`
- `chat_sessions`
- `question_bank_items`
- `practice_attempts`
- `app_settings`

当前正式运行时不支持 MySQL / SQLite 作为主数据库；它们只在历史迁移或历史文档语境中出现。Chroma 也只作为历史迁移来源，当前向量运行时是 PGVector。

## 6. 外部依赖与开关

- `DATABASE_URL`：启动级必需，必须是 PostgreSQL DSN。
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

```bash
cd backend
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests
./.venv313/bin/python scripts/check_do_model_access.py
```

```bash
cd frontend
npm run lint
npm run build
```
