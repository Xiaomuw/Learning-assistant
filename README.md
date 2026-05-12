# 学习助手

一个面向移动端 H5 的 AI 学习助手，当前主栈是 **FastAPI + LangGraph + LangChain + PostgreSQL/PGVector + Next.js**。

产品层统一叫 **notebook / 笔记本**；后端 wire、数据库和部分历史字段仍保留 `subject_id` 兼容命名。当前正式运行时只使用 **PostgreSQL + PGVector**，MySQL / SQLite / Chroma 只作为历史迁移语境保留。

## 当前能力

- 本地账号：邮箱验证码注册、登录、refresh、logout、修改密码。
- Notebook 知识库：PDF、URL、自动章节、题库内容进入 PGVector。
- 主问答：`LearningOrchestratorGraph` 路由 + `QAGraph` + RAG + capability 工具层 + 可选 MCP。
- 练习：4 选 1 单选题、AI 补题、本地题库优先、提交后显示答案和解析。
- 学习分析：三层记忆 + graph-era `LearningEvent / attempts / mastery_snapshots`，旧统计表只作兼容读取。
- 观测：LangSmith 可选开启，主要覆盖 `concept / problem / review` 主问答链路。

## 最短启动

后端默认端口 `8000`，前端默认端口 `3000`。

```bash
cd backend
cp .env.example .env
python -m venv .venv313
source .venv313/bin/activate
pip install -r requirements.txt
python scripts/check_environment.py
python -m app.main
```

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Docker Compose 默认稳定运行模式：

```bash
cp backend/.env.example backend/.env
docker compose up -d --build
```

## 最低自检

```bash
cd backend
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests
```

Graph 相关改动至少补跑：

```bash
make test-graphs
```

```bash
cd frontend
npm run lint
npm run build
```

## 文档入口

建议从 [docs/README.md](docs/README.md) 开始。最常用的接手文档是：

- [docs/ai-handoff.md](docs/ai-handoff.md)：给后续 AI / Agent 的交接卡。
- [docs/project-current-status.md](docs/project-current-status.md)：当前产品和技术事实源。
- [docs/backend-map.md](docs/backend-map.md)：后端目录与主链路。
- [docs/frontend-map.md](docs/frontend-map.md)：前端页面、状态和 API 适配边界。
- [docs/feature-flows.md](docs/feature-flows.md)：登录、RAG、练习、掌握度等流程图。
- [docs/langgraph-overview.md](docs/langgraph-overview.md)：LangGraph 图结构和节点职责。

## 关键维护约定

- 新后端代码只进入 `backend/app/*`，按 `interfaces -> application -> orchestration/domains/services/infrastructure/shared` 分层。
- `interfaces/*` 是唯一 HTTP 翻译层；`application/*` 不直接抛 `HTTPException`。
- Notebook 知识库操作统一走 `backend/app/services/notebook_knowledge_base.py`。
- RAG 正式入口是 `backend/app/services/rag/`；旧 `services/retrieval` 仅保留迁移期薄兼容壳。
- 工具执行正式入口是 `backend/app/services/tooling/` capability 层；旧 `backend/app/services/tools/` 仅保留 provider / legacy adapter 支撑。
- 当前活动模型选择统一走 `backend/app/services/runtime_models.py`。
- 前端页面和组件使用 `Notebook / notebookId`；`subject_id` 只留在 API wire 兼容边界。

## 环境变量提示

真实密钥只写入本机 `backend/.env`，不要写进文档或提交。常用变量请看 [backend/.env.example](backend/.env.example)，包括：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `MODEL_ACCESS_KEY`
- `OPENAI_BASE_URL`
- `SMTP_*`
- `LANGSMITH_*`
- `MCP_*`

如果 SMTP 未配置，注册发码接口会返回明确错误；如果 LangSmith / MCP 未开启，主业务会 fail-open 继续运行。
