# 项目文档总索引

> 目标读者：项目维护者、接手开发同学、协作 AI / Agent  
> 当前事实源：`backend/app/*`、`frontend/app/*`、`frontend/lib/api.ts`、`backend/langgraph.json`

这套文档的原则是：**先读当前事实源，再读历史背景**。如果文档之间出现冲突，以 `project-current-status.md` 和实际代码为准。

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
- [数据库设计](database-design.md) 与 [ER 图](database-er.md)：当前 PostgreSQL 结构、PGVector 说明。
- [LangGraph Platform 部署](langgraph-platform-deployment.md)：Cloud / Studio 部署说明。
- [测试报告](test-reports/full-functional-2026-04-27.md)：最近一次全功能验收与修复记录。

## 历史参考，不作为当前事实源

以下文档保留是为了理解演进过程，里面可能出现 MySQL、SQLite、Chroma、`default_user` 等早期口径：

- [项目需求文档](project-requirements.md)
- [数据库 V2 路线图](database-v2-roadmap.md)
- [数据库示例 SQL](database-examples.md)
- [MySQL 旧 DDL 草案](mysql-current-schema.sql)
- [后端结构审计](backend-architecture-audit.md)

当前正式口径是：

- 数据库：PostgreSQL
- 向量库：PGVector
- 产品语义：notebook
- wire/db 兼容字段：`subject_id`
- 正式用户：真实注册用户，`default_user` 只代表历史/开发兼容数据

## 最低自检命令

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

## 文档维护规则

- 不要把真实 API key、SMTP 授权码、模型密钥写入文档。
- 新文档优先链接到 `backend/app/*` 和 `frontend/*` 的正式入口，不再引用旧顶层后端目录。
- 如果只是历史背景，必须明确标注“历史参考，不作为当前事实源”。
- 涉及 notebook 时，先用产品语义解释，再注明 `subject_id` 是兼容字段。
