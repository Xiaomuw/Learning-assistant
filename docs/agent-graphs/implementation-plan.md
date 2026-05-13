# Agent Graph 分阶段实施计划

> 历史参考说明：这份文档记录 Agent Graph 切换过程中的实施计划与阶段性下一步。当前实现状态请优先看 [Agent Graph 当前状态](status.md)、[Graph Relationship Matrix](graph-relationship-matrix.md) 和实际代码。

## Phase 0：架构基线

- 已完成 Graph 文档集、共享 state/schema、Tool capability 抽象、repository interface、LearningOrchestratorGraph 骨架和 contract 测试。
- 已完成 `make test-graphs` 测试入口。

## Phase 1：QAGraph

- 已完成：`QAGraph` 输出 `FinalResponse`、`EvidenceChunk`、`ToolResult`、`LearningEvent`、`GraphError`。
- 已完成：`ProductionQARuntimeAdapter` 包装 `domains.qa.runtime`，不再暴露旧 graph state。
- 已完成：普通 notebook-only 证据不足、工具失败、模型降级、空回答等 contract 映射测试。
- 已完成：`/api/chat` 默认通过 Orchestrator 调用 QAGraph，不再走旧 workflow 或 shadow。
- 已完成：新增 `notebook_retrieve` capability adapter，QAGraph 可通过 `ToolExecutor / ToolPolicyResolver` 执行 notebook 与 web capability request。
- 已完成：`domains.qa.runtime` 内部 tool loop 已收敛到 capability 工具名，历史 provider 工具名只保留在 adapter/compat 层。
- 下一步：继续把更多 provider 接到统一 `services/tooling` executor，逐步减少 `domains.qa.capability_tools` 对旧实现的直接包装。

## Phase 2：QuestionGenerationGraph

- 已完成：题目蓝图、候选题、answer key、rubric、solver verifier、quality reviewer、dedupe、difficulty calibration 和最小持久化路径。
- 已完成：`QuestionItemRepository` graph-era 实现和 `question_items` facts 表。
- 已完成：质量门补齐唯一答案、source refs、rubric、difficulty、dedupe、空输出和有限 retry。
- 下一步：建立真实题目 dataset eval 与人审样本闭环。

## Phase 3：MasteryEvaluationGraph

- 已完成：消费 `LearningEvent / attempts`、strong/medium/weak signal、hint 降权、bounded update、状态分类和下一步建议。
- 已完成：`MasterySnapshotRepository` graph-era 实现和 `mastery_snapshots` facts 表。
- 已完成：新增历史 `practice_attempts / user_knowledge_stats / question_bank_items` 到 graph-era facts 的幂等 backfill CLI；默认 dry-run，`--execute` 才写入。
- 下一步：在目标环境执行 dry-run 后按需 execute，并用 repository smoke test 验证。

## Phase 4：工具层扩展

- 已完成：业务 Graph 只能请求 capability。
- 已完成：Tavily 只作为 `web_search` provider，不允许业务 Graph 节点直接 import。
- 已完成：补齐 `notebook_retrieve` provider adapter 与风险策略测试。
- 已完成：QA runtime 模型可见工具名统一为 `notebook_retrieve / web_search / web_extract / session_summary / learning_profile / question_recommend`。
- 下一步：按需补 `sql_read / code_execute / file_parse` 的 provider adapter 与更细粒度风险策略。

## Phase 5：PostgreSQL 持久化与观测

- 已完成：graph-era facts 表进入 Alembic migration 管理。
- 已完成：SQL repository factory 提供 `graph_runs / node_runs / tool_runs / learning_events / attempts / mastery_snapshots / question_items / concepts`。
- 已完成：`/api/chat` 新 Orchestrator 执行时可写 graph facts 摘要。
- 已完成：对当前本地 `DATABASE_URL` 运行 `alembic upgrade head` 并验证 facts 表读写。

## Phase 6：联调和 eval

- 已完成：`make eval-graphs` 运行本地 deterministic graph eval runner，默认不依赖真实 LLM、Tavily、生产数据库或 LangSmith；当前覆盖 6 个 QA/QGen/Mastery case。
- 已完成：建立 LangSmith dataset/evaluator 闭环命令，`GRAPH_EVAL_LANGSMITH=true` 时可同步 dataset 并运行 `qa_groundedness / tool_policy_precision / qgen_quality / mastery_stability`。
- 下一步：在真实 LangSmith 项目中执行 `make eval-graphs-remote`，并持续扩展 groundedness、tool precision、question quality、mastery stability 样本。

## Phase 7：旧入口删除与生产收口

- 已完成：删除旧 `app.orchestration.graph`、`app.orchestration.workflow`、chat shadow/runtime selector/fallback 映射。
- 已完成：`backend/langgraph.json` 的 `learning_assistant` 兼容 key 指向 Orchestrator compiled graph。
- 已完成：`/api/chat` 与 `/api/chat/sync` 保持公开 response shape 兼容，但内部只走新 Orchestrator。
- 下一步：在真实环境持续观察 graph facts、LangSmith trace 和本地 eval，逐步移除代码中剩余的兼容命名与历史 adapter。
