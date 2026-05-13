# Agent Graph 当前状态

## 当前结论

- `/api/chat` 与 `/api/chat/sync` 的后端生产入口已切换为 `LearningOrchestratorGraph`。
- `backend/langgraph.json` 继续保留外部兼容 key `learning_assistant`，但它导出的 compiled graph 已指向新 Orchestrator。
- 旧 `backend/app/orchestration/graph/`、`backend/app/orchestration/workflow/`、chat shadow / runtime selector / legacy fallback 映射已从生产代码中删除。
- 领域服务仍保留：`domains.qa`、`domains.practice`、`domains.mastery` 可通过新 Graph adapter 复用，不再作为旧生产图入口。
- Graph-era facts 已进入 Alembic 管理，`Base.metadata.create_all()` 仅保留本地 bootstrap 兼容。

## 已完成

- `docs/agent-graphs/` 文档集已建立，并随本轮切换更新为新 Graph 生产入口语义。
- 共享 contract 事实源为 `backend/app/shared/schemas/agent_graphs.py`，包含 `ConceptRef`、`EvidenceChunk`、`ToolResult`、`LearningEvent`、`FinalResponse`、`GraphError` 和 `LearningEventType`。
- `LearningOrchestratorGraph` 负责请求规范化、上下文加载、意图路由、子图调用、响应组合和审计；不直接生成教学回答、题目或掌握度。
- `QAGraph` 已具备 production runtime adapter：`ProductionQARuntimeAdapter` 包装 `domains.qa.runtime`，输出只暴露新 graph contract。
- `QAGraph` 工具链已完成首批 capability 收口：新增 `notebook_retrieve` provider adapter，复用现有 RAG/context audit，并统一返回 `ToolResult.evidence`；稳定概念默认不触发工具，时效/来源类问题才规划 web capability。
- `QAGraph` 内部主链路已升级为 `ChatQuestionGraph v2`：
  - 节点顺序为 `InputNormalize -> IntentClassifier -> ContextResolver -> KnowledgeRouter -> Retrieval -> EvidenceJudge -> AnswerGenerate -> AnswerQualityCheck -> WebSearch fallback -> EvidenceMerge -> FinalResponse`。
  - `KnowledgeRouter` 支持当前 notebook、课程、显式资料请求和传入的多知识库候选，默认最多选择 3 个知识库。
  - `RetrievalNode` 只通过 `notebook_retrieve` capability 检索知识库；不直接 import provider。
  - `WebSearchNode` 只作为时效补充或质量兜底，在 `AnswerQualityCheck` 判定后最多触发一次，不替代知识库路由。
  - `EvidenceMergeNode` 明确区分 `notebook_evidence` 与 `web_evidence`，并输出 `source_usage=model|notebook|web|mixed`。
- `QuestionGenerationGraph` 已具备生产化骨架：可生成 `QuestionItem`、`QualityReport`、`LearningEvent`，并可通过 repository 持久化题目。
- `QuestionGenerationGraph` 质量门已补强：覆盖唯一答案、source refs、rubric、difficulty、dedupe、空输出与有限 retry；graph contract 不再暴露 `legacy_*` 语义。
- 问答出题意图处理已收口：
  - 新增 `QuizRequestResolver`，可识别“帮我出题 / 再来几道 / 考我一下 / AI补题”等请求，输出稳定 `quiz_request` contract。
  - Orchestrator 在路由前先解析出题意图；信息完整时进入 `QuestionGenerationGraph`，信息不足时返回 `QuizClarificationPanel`，普通问题继续进入 QAGraph。
  - 新增 `PracticePackService` 与 `POST /api/practice/packs`，刷题页可基于当前题目知识点直接 AI 补题。
  - `/api/chat` 兼容保留原响应 shape，并新增可选 `quiz_request / quiz_clarification` 字段；问答模块不维护完整刷题状态。
- `MasteryEvaluationGraph` 已具备 bounded mastery update，消费 `LearningEvent / attempts`，只有它可以写 `mastery_snapshots`。
- 已新增幂等 backfill CLI：`backend/.venv313/bin/python -m app.persistence.backfill_graph_facts --dry-run|--execute`，可把旧 `practice_attempts / user_knowledge_stats / question_bank_items` 映射到 graph-era facts。
- `backend/app/services/tooling/` 已提供 capability-based 工具层；业务 Graph 只能请求 `ToolCapability`，不能直接 import Tavily provider。
- `backend/app/persistence/interfaces.py` 已定义 repository Protocol；Graph 副作用必须通过 repository。
- `backend/app/persistence/repositories/graph_facts.py` 已提供 graph-era SQL repository factory。
- graph-era facts 表包括：`graph_runs`、`node_runs`、`tool_runs`、`learning_events`、`attempts`、`mastery_snapshots`、`question_items`、`concepts`。
- `make test-graphs` 已覆盖 contract、tooling、orchestrator、cross graph、QA/QGen/Mastery adapter、migration 与 graph persistence 测试。
- `make eval-graphs` 已从占位改为本地 deterministic graph eval runner；默认不依赖真实 LLM、Tavily、生产数据库或 LangSmith。

## 本轮生产入口切换

- `backend/app/application/chat/service.py` 现在统一调用 `run_orchestrator_chat()`。
- `run_orchestrator_chat()` 负责：
  - 构造 Orchestrator state。
  - 调用 `LearningOrchestratorGraph`。
  - 将 `FinalResponse` 映射回当前兼容的 `ChatResponse / SSE` shape。
  - 写入 graph facts 摘要。
  - 通过 LangSmith run name `chat.orchestrator.sync` / `chat.orchestrator.sse` 记录脱敏 trace。
- 新图失败时返回新 Graph 的结构化错误响应；不再回退旧 workflow。
- 已删除的旧生产映射包括：
  - `app.orchestration.graph`
  - `app.orchestration.workflow`
  - `app.application.chat.graph_runtime`
  - `app.application.chat.qagraph_shadow`
  - `app.application.chat.workflow_adapter`

## 数据库与事实表

- Alembic migrations 位于 `backend/alembic/versions/`，graph-era facts、微信身份、KB taxonomy、practice question、PGVector hardening、auth core、idempotency 和 readiness/index 相关变更都应以当前 Alembic head 为准。
- `backend/alembic/env.py` 会加载 `backend/.env`，用于读取当前本地 `DATABASE_URL`。
- graph facts 默认随新 Orchestrator 执行写入；`ENABLE_GRAPH_FACTS=false` 可在测试或诊断场景关闭。
- 旧领域服务仍可读取原有业务数据；历史业务数据已具备幂等 backfill 工具，默认 dry-run，`--execute` 才写入当前 `DATABASE_URL`。
- 历史本地快照：曾在某次本地 `DATABASE_URL` 上执行 backfill，dry-run 计划 788 项；execute 后再次执行结果为 `inserted_count=0, skipped_count=788, error_count=0`，当时 graph-era 计数为 `attempts=9, mastery_snapshots=25, question_items=360, concepts=166`。这些数字只说明当时环境，不代表当前数据库健康状态。

## LangSmith / Eval

- 新聊天入口的 LangSmith 根 run：
  - `chat.orchestrator.sync`
  - `chat.orchestrator.sse`
- 子图语义 run：
  - `qagraph.run`
  - `qgen.run`
  - `mastery.run`
- 工具观测只保存 capability/provider/status/latency/count 等摘要，不保存 notebook 原文、完整 prompt、tool args 或网页正文。
- `graph_runs.langsmith_run_id` / `sampled` 已为 Postgres 与 LangSmith 对齐预留。
- Graph eval case registry 已成为本地 `make eval-graphs` 与远程 LangSmith dataset/evaluator 的共同事实源。
- 新增远程评测命令：
  - `cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --sync`
  - `cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --run`
  - `cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --all`
  - `make eval-graphs-remote`
- `GRAPH_EVAL_LANGSMITH=true` 时才会同步 dataset 并运行 LangSmith evaluator；默认本地 eval 不访问网络、不依赖 LangSmith。
- 远程 evaluator 只上传脱敏摘要字段：case name、graph type、状态、计数、错误类型和耗时；不上传用户原文、答案全文、notebook 原文、完整 prompt 或 tool args。
- 已新增 deterministic evaluators：`qa_groundedness`、`tool_policy_precision`、`qgen_quality`、`mastery_stability`。
- `make test-graphs` 会强制关闭 LangSmith tracing，避免离线环境下测试通过后仍被远程上传重试阻塞；`make eval-graphs` 默认离线，只有显式设置 `GRAPH_EVAL_LANGSMITH=true` 才尝试远程 eval trace。

## QA Runtime Capability 收口

- `domains.qa.runtime` 的工具循环已改为暴露 capability 工具名：
  - `notebook_retrieve`
  - `web_search`
  - `web_extract`
  - `session_summary`
  - `learning_profile`
  - `question_recommend`
- 旧 notebook / Tavily / MCP / profile / recommendation 实现保留在 `capability_tools` adapter 内部，作为 provider/compat 层，不再进入新 Graph contract、LangSmith metadata 或新生成的过程摘要。
- `domains.qa.tool_loop` 已按 `ToolCapability` / provider 摘要判断 source usage、tool decision 和 trace metadata，不再基于历史 provider 工具名分支。
- 工具 run 记录 capability/provider/status/doc_count/payload_keys，不记录完整 tool args 或正文。

## 历史测试记录（点时快照）

以下命令和数量记录的是当次切换验收快照，不代表当前工作树已经通过。每轮相关修改仍应重新运行对应测试。

已通过的最小切换测试：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_chat_api backend.tests.test_workflow_routes backend.tests.test_qa_graph_adapter backend.tests.test_qa_graph_runtime_adapter backend.tests.test_quiz_flow_nodes
```

本轮出题意图与澄清流程验证：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_quiz_request_resolver backend.tests.test_learning_orchestrator_graph backend.tests.test_question_generation_graph_adapter backend.tests.test_chat_api backend.tests.test_practice_api
backend/.venv313/bin/python -m unittest backend.tests.test_workflow_routes
```

已通过的 migration / repository 测试：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_graph_migrations backend.tests.test_graph_persistence_repositories
```

已通过的 Graph 回归：

```bash
make test-graphs
make eval-graphs
```

当时 `make test-graphs` 覆盖 110 个 Graph / contract / persistence / backfill / eval / quiz request 用例；`make eval-graphs` 覆盖 6 个本地 deterministic eval case。

已通过的完整后端回归：

```bash
env LANGSMITH_TRACING=false backend/.venv313/bin/python -m unittest discover -s backend/tests
```

当时完整后端回归结果：360 个测试通过，5 个按测试条件跳过。

已验证远程 eval CLI 在默认关闭状态下只输出脱敏 preview，不访问网络：

```bash
cd backend && GRAPH_EVAL_LANGSMITH=false LANGSMITH_TRACING=false ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --all
```

如触及前端或公开 TypeScript 类型，再执行：

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

该快照也曾额外执行上述前端检查，均通过。

## 剩余风险

- 真实 LangSmith 远程 evaluator/dataset 需要网络、`LANGSMITH_API_KEY` 和目标项目配置；默认测试只验证 CLI、dataset payload 和 evaluator 调用闭环，不会触网。
- `QuestionGenerationGraph` 已具备生产质量门与有限 retry；正式题库质量仍需要持续积累 LangSmith dataset / 人审样本来校准。
- Backfill 已具备 dry-run、execute 和幂等测试；真实环境执行前仍建议先看 dry-run 计数，避免把不需要的旧实验数据复制到 graph-era facts。
