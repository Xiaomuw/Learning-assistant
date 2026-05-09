# Codex 工作规则

## 1. 项目背景

- 当前项目是 `FastAPI + LangGraph + LangChain + PostgreSQL/PGVector + Next.js`。
- 生产入口已切换为 `LearningOrchestratorGraph`；`/api/chat` 不再走旧 `learning_assistant` 生产图。
- 新的企业级 Graph 架构放在 `backend/app/orchestration/graphs/`。
- 当前已建立 `docs/agent-graphs/`、统一 schema、tooling capability 层、repository Protocol。
- 后续所有解释、计划、测试总结、变更总结都必须使用中文回答用户。代码、文件名、类名、函数名、API 名、数据库表名可以保持英文。

## 2. Graph 边界

- `LearningOrchestratorGraph` 只负责路由、上下文加载、响应组合、审计。
- `QAGraph` 只负责问答、证据判断、工具 fallback、grounding、`LearningEvent`。
- `QuestionGenerationGraph` 只负责出题、验证、质量检查、题目持久化。
- `MasteryEvaluationGraph` 只负责消费 `LearningEvent` / `attempts` 并更新 mastery。
- `ToolExecution` 层必须通过 capability，不允许业务 Graph 节点硬编码 Tavily。

## 3. 修改边界

- `/api/chat` 必须保持现有公开协议兼容，但内部默认使用 `LearningOrchestratorGraph`。
- 旧 `learning_assistant` 生产图入口已废弃；不要重新引入旧 graph/workflow/shadow fallback 映射。
- graph-era facts 表由 Alembic 管理；生产 schema 变更必须提供 migration。
- 不要把 DB connection、LLM client、tool instance 放进 Graph State。
- 不要把长期业务事实只存在 LangGraph checkpoint。
- 不要让 `QAGraph` 或 `QuestionGenerationGraph` 直接写 `mastery_snapshots`。
- 不要让任何业务 Graph 节点直接 import Tavily provider。
- 不要引入无限 retry / repair loop。

## 4. 测试命令

- 每轮相关修改后先跑最小测试。
- 然后跑：

```bash
make test-graphs
```

- 如果修改前端或共享接口，再跑：

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

- 如果前端 dev server 正在运行，执行 `npm run build` 后必须重启 dev server 再浏览器复测；`next build` 会重写 `frontend/.next`，继续沿用旧 dev server 可能出现 `Cannot find module './*.js'` 这类本地缓存错位错误。
- `make eval-graphs` 目前运行本地 deterministic graph smoke eval；不要声称 LangSmith dataset/evaluator 真实 eval 已通过，除非已经显式运行对应评测。

## 5. 子代理协作规则

- shared schema、tooling、repository、orchestrator 只能由主代理或 Contract Reviewer 建议后修改。
- `QAGraph Worker`、`QuestionGenerationGraph Worker`、`MasteryEvaluationGraph Worker` 不能各自修改 shared contract。
- 每个 worker 必须说明自己产生或消费的 `LearningEvent`。
- 每个 worker 必须说明自己读写的 repository。
- 每个 worker 必须说明自己需要的 tool capability。
- 所有最终回答、计划、总结都用中文。
