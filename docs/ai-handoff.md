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

- 本地 FastAPI 使用 `backend/app/orchestration/graph/graph.py`
- Platform sidecar 使用 `backend/langgraph.json` 和 `backend/app/orchestration/platform/*`
- 当前正式图名是 `learning_assistant`
- 当前核心拓扑是 `preflight_node -> router -> rag_node/分支节点 -> qa_agent_node/专项节点 -> memory_node/graph_error_node -> finalize_node -> END`

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
cd backend
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests
./.venv313/bin/python scripts/check_do_model_access.py
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
- 聊天问答：`interfaces/api/chat.py -> application/chat/* -> orchestration/workflow -> graph -> rag_node -> qa_agent -> domains/qa/runtime.py`
- RAG：`orchestration/agents/rag.py -> services/rag/rag_service.py -> services/rag/{retriever,vector_store}.py`
- Notebook 入库：`interfaces/api/upload.py or subjects.py -> application/ingest or notebooks -> services/notebook_knowledge_base.py`
- 练习：`interfaces/api/practice.py -> application/practice/service.py -> domains/practice/*`
- 掌握度：聊天 exposure 和做题 attempt 更新 `domains/mastery/service.py` 与 `user_knowledge_stats`

LangGraph 节点边界：

- `preflight_node`：只做输入规范化、空问题/超长问题/缺失 ID 的图级校验。
- `router`：只做问题分类。
- `rag_node`：只做 notebook 检索、诊断和 RAG 上下文写入，失败时 fail-open。
- `qa_agent_node`：只进入 QA runtime，复用 `rag_node` 产出的上下文并负责最终回答。
- `quiz_gen`：只做题包生成。
- `mcq_solver`：只做聊天页单选题判题。
- `meta_node`：只做寒暄和系统/能力类问题。
- `memory_node`：只更新记忆；失败只写 warning，不覆盖主回答。
- `graph_error_node`：只处理未被 runtime 降级吸收的图级异常。
- `finalize_node`：统一写 `finalized`、`final_response_type`、`route_decision`。

## 外部依赖

- DigitalOcean Model Access：OpenAI-compatible chat / embedding。
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
