# 项目文档总索引

> 目标读者：项目维护者、接手开发同学、协作 AI / Agent  
> 当前事实源：`backend/app/*`、`frontend/app/*`、`frontend/lib/api.ts`、`backend/langgraph.json`

这套文档的原则是：**先读当前事实源，再读历史背景**。如果文档之间出现冲突，以 `project-current-status.md`、Alembic migration、实际 API route 和代码为准。

## 先读这 4 份

1. [AI 交接卡](ai-handoff.md)  
   给后续 AI / Agent 的快速接手说明，包含禁区、命令、正式入口和测试数据约定。
2. [项目当前状态](project-current-status.md)  
   当前产品能力、技术栈、外部集成、数据库事实源和已知边界。
3. [后端目录能力地图](backend-map.md)  
   后端每层职责、聊天主链路、RAG / Tool / LangGraph 入口。
4. [功能流程图](feature-flows.md)  
   登录注册、Notebook 入库、RAG、练习、知识点掌握度、Profile/Dashboard 数据流。

## 按需阅读

- [前端目录能力地图](frontend-map.md)：Next 页面、AuthProvider、API 适配层、Notebook 命名边界。
- [LangGraph 工作流总览](langgraph-overview.md)：图结构、节点职责、Platform sidecar。
- [后端维护约定](backend-maintenance-guide.md)：分层规则、禁止事项、最低自检。
- [API 参考](api-reference.md)：当前 HTTP 接口形状。
- [RAG 知识库内容 AI 工作说明](rag-knowledge-content-ai.md)：PDF 资料治理、notebook 入库、状态检查和抽检报告规范。
- [数据库设计](database-design.md) 与 [ER 图](database-er.md)：当前 PostgreSQL 结构、PGVector 说明。
- [LangGraph Platform 部署](langgraph-platform-deployment.md)：Cloud / Studio 部署说明。

## 历史参考，不作为当前事实源

以下文档保留是为了理解演进过程，里面可能出现 MySQL、SQLite、Chroma、`default_user` 等早期口径：

- [项目需求文档](project-requirements.md)
- [数据库 V2 路线图](database-v2-roadmap.md)
- [数据库示例 SQL](database-examples.md)
- [MySQL 旧 DDL 草案](mysql-current-schema.sql)
- [后端结构审计](backend-architecture-audit.md)
- [Agent Graph 分阶段实施计划](agent-graphs/implementation-plan.md)
- [测试报告 2026-04-27](test-reports/full-functional-2026-04-27.md)
- [测试报告 2026-05-08](test-reports/full-functional-2026-05-08.md)
- [测试报告 2026-05-10](test-reports/full-functional-2026-05-10.md)
- [代码审查 2026-05-10](reviews/code-review-2026-05-10.md)

当前正式口径是：

- 数据库：PostgreSQL
- 向量库：PGVector
- 产品语义：notebook
- wire/db 兼容字段：`subject_id`
- 正式用户：真实注册用户，`default_user` 只代表历史/开发兼容数据

## 最低自检命令

建议在 repo root 使用统一入口：

```bash
make check-project
```

如需分阶段排查，可以拆开运行：

```bash
make test-backend
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/test_db make test-backend-postgres
make test-graphs
make eval-graphs
make smoke-backend
make check-frontend
make check-weapp
```

后端验收口径要区分清楚：

- `/health` 只证明 FastAPI 进程能响应，不证明数据库、PGVector、认证、模型或 LangGraph runtime 已就绪。
- `backend/scripts/check_environment.py` 检查启动级配置和可选依赖提示，不等于已完成 authenticated runtime smoke。
- `make test-backend-postgres` 必须显式提供真实 PostgreSQL `TEST_DATABASE_URL`；关键 Postgres 集成测试在该目标下不会静默跳过，会创建并删除临时 schema。
- `make smoke-backend` 会访问正在运行的后端，默认创建临时认证用户，登录后检查 `/api/auth/me`、`/api/subjects`、`/api/users/{id}/learning-center`、`/api/users/{id}/practice/recommendations`，结束时清理该账号；它会写入当前后端连接的本地数据库。
- `make eval-graphs` 是本地 deterministic graph smoke eval；只有显式运行 `make eval-graphs-remote` 或对应 LangSmith CLI 时，才能声称 LangSmith remote dataset/evaluator 通过。

如果已经在 `backend/` 目录内，再使用 backend 相对路径：

```bash
./.venv313/bin/python scripts/check_environment.py
./.venv313/bin/python -m compileall app tests scripts
./.venv313/bin/python -m unittest discover -s tests -t .
POSTGRES_TEST_STRICT=true TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/test_db ./.venv313/bin/python -m unittest tests.test_auth_api tests.test_repository_init tests.test_practice_question_import
./.venv313/bin/python scripts/smoke_backend.py --base-url http://127.0.0.1:8000
```

```bash
cd frontend
npm run lint
npm run build
```

## 文档维护规则

- 不要把真实 API key、SMTP 授权码、模型密钥写入文档。
- 新文档优先链接到 `backend/app/*` 和 `frontend/*` 的正式入口，不再引用旧顶层后端目录。
- 如果只是历史背景，必须明确标注“历史参考，不作为当前事实源”。
- 涉及 notebook 时，先用产品语义解释，再注明 `subject_id` 是兼容字段。
