# Graph Contracts

## BaseLearningState

所有新 Graph 共享 `BaseLearningState`。字段必须可 JSON 序列化，并适合 LangGraph checkpoint。

必备字段：

- `run_id`
- `tenant_id`
- `user_id`
- `notebook_id`
- `course_id`
- `thread_id`
- `graph_type`
- `graph_version`
- `source_policy`
- `user_message`
- `messages`
- `concepts`
- `evidence`
- `tool_results`
- `learning_events`
- `final_response`
- `errors`

禁止放入 State：

- 数据库连接
- SQLAlchemy Session
- LLM client / model instance
- tool instance
- 不可序列化 callback / coroutine / file handle

## Graph 类型

- `orchestrator`
- `qa`
- `question_generation`
- `mastery`

## Source Policy

- `notebook_only`：只能使用 Notebook 或课程资料。
- `notebook_plus_external`：可以使用 Notebook 和外部资料。
- `open_tools`：允许按工具策略调用开放工具。

## Graph I/O

### LearningOrchestratorGraph

- Input：用户消息、用户/线程/notebook 标识、source policy。
- Output：统一 `FinalResponse`、路由结果、审计事件。

### QAGraph

- Input：用户问题、学习上下文、source policy、可用工具 capability。
- Output：教学回答、证据引用、学习事件。

### QuestionGenerationGraph

- Input：目标知识点、难度、题型、约束、可用资料。
- Output：题目条目、质量报告、学习事件。

### MasteryEvaluationGraph

- Input：学习事件、答题记录、历史掌握度。
- Output：掌握度快照、弱信号、下一步建议。

## FinalResponse

统一最终响应结构：

- `answer`
- `source_level`
- `concepts`
- `evidence_refs`
- `coach_actions`
- `mastery_signals`
- `ui_payload`

## LearningEvent

统一学习事件结构：

- `id`
- `event_type`
- `user_id`
- `concept_id`
- `graph_run_id`
- `payload`
- `created_at`

## Version 记录

每次 Graph run 应记录：

- `graph_type`
- `graph_version`
- `prompt_version`
- `model_version`
- `tool_version`

这些字段进入 Graph State、LangSmith metadata 和 graph run 记录。

当前 `graph_runs` 表已经落地，已包含 `graph_type / graph_version / metadata_json` 等字段；`prompt_version / model_version / tool_version` 如需保存，应放入 `metadata_json` 或通过后续 Alembic migration 明确扩展，不能假设现表已有同名列。
