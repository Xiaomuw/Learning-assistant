# Agent Graph 目标架构

## 目标

当前项目的生产入口已切换为 `LearningOrchestratorGraph`。`backend/langgraph.json` 继续保留外部兼容 key `learning_assistant`，但该 key 指向的新 compiled graph 是 Orchestrator，而不是旧单体生产图。目标架构是在现有 `backend/app` 分层内让问答、出题、掌握度以独立 Graph 演进，并通过统一 contract、repository 和观测体系协作。

## Graph 边界

### LearningOrchestratorGraph

- 负责请求规范化、上下文加载、意图识别、Graph 路由、最终响应组合、统一审计。
- 不直接生成教学回答。
- 不直接生成题目。
- 不直接更新掌握度。
- 调用下游 Graph，并把结果组合成统一 `FinalResponse` 和现有 `/api/chat` 兼容响应。

### QAGraph

- 负责问答、辅导、Notebook 检索、证据判断、工具 fallback、grounded answer generation、grounding verifier、answer repair、学习事件记录。
- 只写 `LearningEvent`，不直接写 `mastery_snapshots`。
- Notebook 是辅助证据；只有 `source_policy=notebook_only` 时才成为强依据。

### QuestionGenerationGraph

- 负责题目蓝图、候选题生成、答案生成、solver verifier、quality reviewer、dedupe、difficulty calibration、题目持久化。
- 只写 `question_items` 和必要的生成审计事件。
- 不直接更新用户掌握度。

### MasteryEvaluationGraph

- 负责消费学习事件、答题评分、弱信号提取、掌握度更新、先修知识传播、状态分类、下一步学习推荐。
- 只有这个 Graph 可以写 `mastery_snapshots`。
- 不生成完整教学回答，不生成题目正文。

### ToolExecutionSubgraph / 统一工具执行层

- Graph 只能请求 capability，例如 `web_search`、`notebook_retrieve`。
- Provider 由 registry/policy 决定，例如 Tavily 是 `web_search` 的一个 provider。
- 工具执行统一产出 `ToolResult` 和 `tool_run` 审计。

## 生产入口

- `/api/chat` 和 `/api/chat/sync` 默认进入 `LearningOrchestratorGraph`。
- LangGraph Platform 的兼容导出名仍为 `learning_assistant`，但底层 graph 已指向 Orchestrator。
- 旧 graph/workflow/shadow/fallback 生产映射已废弃，不再作为回退路径。
- 可复用领域服务仍保留，例如 `domains.qa.runtime`、practice generation、mastery domain service；它们只能通过新 Graph adapter 暴露 contract 输出。

## 解耦方式

三个业务 Graph 通过 `LearningEvent` 解耦：

- QAGraph 产生 `concept_explained`、`question_answered`、`evidence_used` 等事件。
- QuestionGenerationGraph 产生 `question_generated`、`question_reviewed` 等事件。
- MasteryEvaluationGraph 消费事件并产生 `mastery_updated`、`next_step_recommended` 等事件。

## 持久化边界

- PostgreSQL domain tables 是长期业务事实来源。
- LangGraph checkpoint 只负责运行恢复、短期状态和线程续跑。
- 不把长期业务事实只存入 checkpoint。
- Graph State 只能保存可序列化数据，不保存数据库连接、模型实例或工具实例。
