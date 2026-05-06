# LangGraph Platform 部署说明

> 当前策略：LangSmith Cloud / GitHub 部署 + sidecar 模式。  
> 现有 FastAPI `/api/chat*` 不切到远程 Graph API。

## 入口

- Graph 配置：`backend/langgraph.json`
- Graph 名称：`learning_assistant`
- Graph 导出：`backend/app/orchestration/platform/graph.py`
- Platform lifespan app：`backend/app/orchestration/platform/webapp.py`

`platform/graph.py` 只编译当前 `StateGraph`，不使用 FastAPI runtime 里的自管 `PostgresSaver`。LangGraph Platform 会负责 Agent Server 的运行时持久化。

## 本地验证

```bash
python -m venv /tmp/learning-assistant-langgraph-cli
/tmp/learning-assistant-langgraph-cli/bin/pip install "langgraph-cli[inmem]"
cd backend
/tmp/learning-assistant-langgraph-cli/bin/langgraph dev --no-browser
```

不要把 `langgraph-cli[inmem]` 安装进项目的 `.venv313`。当前项目锁定 `langgraph==0.4.1`，而新版 CLI 会拉起更高版本的 LangGraph / LangChain 依赖，适合放在隔离 CLI 环境里运行。

验证重点：

- Studio 能看到 `learning_assistant`
- 节点包含 `router / rag_node / qa_agent_node / quiz_gen / mcq_solver / meta_node / memory_node / graph_error_node`
- `smalltalk / concept / review / practice / mcq_problem` 都能启动 run
- 模拟节点异常时进入 `graph_error_node`

## Cloud 部署

在 LangSmith Cloud 创建 Deployment：

- Repository：`Xiaomuw/Learning-assistant`
- Branch：`main`
- Config path：`backend/langgraph.json`
- Deployment type：先用 Development

必须配置为 secrets 或环境变量：

- `DATABASE_URL`：公网可访问 PostgreSQL + PGVector
- `JWT_SECRET_KEY`
- `OPENAI_API_KEY` 或 `MODEL_ACCESS_KEY`
- `OPENAI_BASE_URL`
- `LANGSMITH_TRACING=true`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGSMITH_ENDPOINT`

可选能力：

- `SMTP_*`：只影响邮箱验证码注册
- `MCP_*`：只影响外部 MCP 工具增强

## 数据库要求

Cloud 不能访问本机 `127.0.0.1:5432`。`DATABASE_URL` 必须指向 LangSmith Cloud 可访问的 PostgreSQL 实例，并且数据库用户需要有创建/启用 `vector` 扩展的权限。

如果数据库不可达：

- Platform app 会启动失败或在 lifespan 阶段报错
- Studio run 中 RAG、记忆、题库相关节点无法完整工作

## 错误策略

- QA runtime 内部可降级的 tool / structured / RAG 错误不会上抛成图级失败
- 核心节点未处理异常会写入脱敏 `graph_error` 并进入 `graph_error_node`
- `memory_node` 失败只写入 `graph_warnings`，不覆盖已经生成的回答
- state 和响应中不写入 API key、数据库 DSN、邮箱等敏感信息

## 验收

部署成功后在 Studio 中测试：

- `你好`
- `什么是 HTTP？`
- `帮我复习 HTTP 缓存`
- `给我出一道 HTTP 单选题`
- `HTTP 默认端口是？ A. 20 B. 53 C. 80 D. 443`

验收标准：

- 图结构清晰可见
- trace 中能看到节点耗时 `node_timings`
- 错误路径能进入 `graph_error_node`
- 现有 FastAPI 前端链路不受影响
