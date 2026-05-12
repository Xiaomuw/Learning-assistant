# AI 接手交接卡

> 给后续协作 AI / Agent 的快速上下文。先读这份，再按需跳到 `project-current-status.md`、`backend-map.md`、`frontend-map.md`。

## 当前项目是什么

这是一个移动端 H5 学习助手：

- 前端：Next.js 14 App Router。
- 后端：FastAPI + LangGraph + LangChain。
- 数据库：PostgreSQL。
- 向量库：PGVector。
- 主能力：账号、Notebook 知识库、RAG 问答、选择题练习、知识点掌握度、LangSmith 观测、可选 MCP。

产品语义叫 **notebook / 笔记本**。后端 wire / DB 里仍有 `subject_id`，这是兼容命名，不要把 `subject` 当产品概念继续扩散。

## 正式入口

后端只看：

- `backend/app/main.py`
- `backend/app/interfaces/*`
- `backend/app/application/*`
- `backend/app/orchestration/*`
- `backend/app/domains/*`
- `backend/app/services/*`
- `backend/app/infrastructure/*`
- `backend/app/shared/*`

前端只看：

- `frontend/app/*`
- `frontend/components/*`
- `frontend/lib/api.ts`
- `frontend/lib/learning-store.ts`
- `frontend/middleware.ts`

LangGraph：

- 本地 FastAPI 使用 `backend/app/orchestration/graphs/orchestrator/graph.py`
- Platform sidecar 使用 `backend/langgraph.json` 和 `backend/app/orchestration/platform/*`
- 当前正式图名是 `learning_assistant`
- 当前核心拓扑是 `LearningOrchestratorGraph -> QAGraph / QuestionGenerationGraph / MasteryEvaluationGraph -> response_composer`

## 不要做什么

- 不要把真实密钥写进 README、docs、测试报告或日志。
- 不要恢复旧顶层后端目录作为主入口。
- 不要在 `application/*` 里直接抛 `HTTPException`。
- 不要在 `interfaces/*` 里直接操作 DB repo、PGVector、LLM provider。
- 不要把 `default_user` 当正式运行用户。
- 不要把 MySQL / SQLite / Chroma 当当前运行主链路。
- 不要把前端组件层改回 `Subject` 主语义。

## 常用命令

后端：

```bash
make test-backend
make test-graphs
make eval-graphs
```

如果已经进入 `backend/` 目录：

```bash
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests -t .
```

前端：

```bash
cd frontend
npm run lint
npm run build
```

本地服务：

```bash
cd backend
./.venv313/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## 当前核心流程

- 登录注册：`interfaces/auth/router.py -> application/auth/service.py -> infrastructure/auth + db repositories`
- 聊天问答：`interfaces/api/chat.py -> application/chat/* -> orchestration/graphs/orchestrator -> QAGraph -> domains/qa/runtime.py`
- RAG：`QAGraph -> services/tooling -> services/rag/{retriever,vector_store,rag_service}.py`
- Notebook 入库：`interfaces/api/upload.py or subjects.py -> application/ingest or notebooks -> services/notebook_knowledge_base.py`
- 练习：`interfaces/api/practice.py -> application/practice/service.py -> QuestionGenerationGraph / domains/practice/*`
- 掌握度：`MasteryEvaluationGraph` 消费 `LearningEvent / attempts` 并写入 `mastery_snapshots`；旧 `user_knowledge_stats` 只作兼容读取

Graph 边界：

- `LearningOrchestratorGraph`：只负责请求守卫、上下文加载、意图路由、子图调用、响应组合与审计。
- `QAGraph`：只负责问答、证据判断、工具 fallback、grounding 和 `LearningEvent`。
- `QuestionGenerationGraph`：只负责出题、验证、质量检查和题目持久化。
- `MasteryEvaluationGraph`：只负责消费 `LearningEvent` / attempts 并更新 mastery。
- `qa_agent_node` 等名称只作为 SSE/presenter 兼容事件名保留，不代表旧 Python agents 包仍在运行。

## 外部依赖

- DeepSeek / OpenAI-compatible chat provider；embedding 独立使用当前配置的 Google 或 OpenAI-compatible provider。
- SMTP：邮箱验证码注册，未配置时注册发码会明确失败。
- LangSmith：可选 tracing，主业务 fail-open。
- MCP：可选 HTTP MCP，主业务 fail-open。

## 测试数据规则

- 使用 `codex-test-*` 前缀创建临时 notebook / 会话 / 测试数据。
- 不删除用户已有数据。
- 如果要删除 notebook、会话、文件或账号，必须单独确认。
- SMTP 真实发码会向外部邮箱发送验证码，测试前要确认目的邮箱和次数。

## 判断文档是否过期

如果某份文档提到 MySQL、SQLite、Chroma、`default_user` 正式运行、旧 `backend/api` / `backend/tools` 主入口，请先当历史背景看。当前事实以：

- [project-current-status.md](project-current-status.md)
- [backend-map.md](backend-map.md)
- [frontend-map.md](frontend-map.md)
- 实际代码

为准。
