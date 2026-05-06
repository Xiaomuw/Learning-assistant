# Persistence Contracts

## 基本原则

- PostgreSQL domain tables 是长期业务事实来源。
- LangGraph checkpoint 只负责运行恢复、短期状态和线程续跑。
- 所有副作用集中在 `persist_*` 节点或 repository 层。
- Graph State 不保存数据库连接或 ORM 对象。

## Graph-era facts 表

- `graph_runs`
- `node_runs`
- `tool_runs`
- `learning_events`
- `mastery_snapshots`
- `attempts`
- `question_items`
- `concepts`

上述表已在 SQLAlchemy model 层落地，路径为 `backend/app/infrastructure/db/models.py`。Graph-era facts 的 schema 现在进入 Alembic 管理，基线 migration 为 `backend/alembic/versions/0001_graph_facts.py`。`Base.metadata.create_all()` 继续作为本地 bootstrap 兼容，不再作为 graph-era 生产 schema 变更的唯一机制。

后续仍建议补充：

- `notebook_chunks`

当前已有相近表：

- `question_bank_items`
- `practice_attempts`
- `user_knowledge_stats`
- `chat_sessions`

## Repository Interface

Graph 只依赖 Protocol：

- `GraphRunRepository`
- `LearningEventRepository`
- `ToolRunRepository`
- `QuestionItemRepository`
- `AttemptRepository`
- `MasterySnapshotRepository`
- `NotebookChunkRepository`
- `ConceptRepository`

已落地的 SQL repository：

- `SqlGraphRunRepository`
- `SqlLearningEventRepository`
- `SqlToolRunRepository`
- `SqlAttemptRepository`
- `SqlMasterySnapshotRepository`
- `SqlQuestionItemRepository`
- `SqlConceptRepository`
- `CompositeAttemptRepository`
- `CompositeMasterySnapshotRepository`

保留的兼容 repository adapter：

- `LegacyQuestionBankItemRepository`：把 `QuestionItemRepository` 映射到旧 `question_bank_items`。
- `LegacyPracticeAttemptRepository`：把旧 `practice_attempts` 读取为 graph-era attempt payload。
- `LegacyKnowledgeStatsMasteryRepository`：把旧 `user_knowledge_stats` 读取为 graph-era mastery snapshot，默认只读。

内部 factory：

- `build_graph_fact_repositories()`

## 写入边界

- QAGraph：只能写 `learning_events`，不直接写 `mastery_snapshots`。
- QuestionGenerationGraph：只能写 `question_items` 和生成审计，不直接写 `mastery_snapshots`。
- MasteryEvaluationGraph：负责写 `mastery_snapshots`。
- LearningOrchestratorGraph：只写运行审计和路由审计，不写领域事实。

## Checkpoint 边界

可进入 checkpoint：

- 当前 Graph state
- 短期路由结果
- 节点中间结果
- 可恢复的工具执行摘要

不可只存在 checkpoint：

- 长期学习事件
- 掌握度快照
- 题目事实
- 用户答题记录
- Notebook chunk 索引事实

## 默认运行策略

- `/api/chat` 默认由 `LearningOrchestratorGraph` 执行并写入 graph facts 摘要。
- `ENABLE_GRAPH_FACTS=true`：默认写 `graph_runs / node_runs / learning_events / tool_runs` 等摘要事实；测试或诊断可显式设为 `false`。
- `ENABLE_GRAPH_DUAL_WRITE=false`：旧 practice API 若仍保留，可选择是否额外写 graph-era `attempts / learning_events`。
- `GRAPH_EVAL_LANGSMITH=false`：默认本地 deterministic eval 不发送 LangSmith trace；显式开启后只发送脱敏摘要。
- 不再保留旧 `/api/chat` shadow/canary/runtime selector；新图失败时返回新 Graph 的结构化错误响应。

## 脱敏与摘要

- `tool_runs.output_summary` 只保存工具输出摘要和 `payload_keys / doc_count` 等结构化字段，不保存完整网页、notebook 原文或 tool args。
- `tool_runs.evidence_refs` 只保存 evidence id/source/score，不保存 evidence text。
- `graph_runs.inputs_summary / outputs_summary` 只保存结构化摘要。
- `learning_events.payload` 作为学习事实保存，但 repository 会对常见原文字段如 `answer / question / content / document / raw_output` 做摘要化处理。
