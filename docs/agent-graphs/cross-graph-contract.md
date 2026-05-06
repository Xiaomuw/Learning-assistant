# Cross Graph Contract

## 目标

本文件校准 `QAGraph`、`QuestionGenerationGraph`、`MasteryEvaluationGraph` 与 `LearningOrchestratorGraph` 的关系。当前 `/api/chat` 已由 `LearningOrchestratorGraph` 承接；`learning_assistant` 仅作为 LangGraph Platform 兼容导出名保留。

## 输入 / 输出关系

### LearningOrchestratorGraph

- 输入：用户消息、`user_id`、`thread_id`、`notebook_id`、`course_id`、`source_policy`。
- 输出：统一 `FinalResponse`、`intent_decision`、`audit_events`。
- 路由目标：
  - `qa` -> `QAGraph`
  - `generate_question` -> `QuestionGenerationGraph`
  - `evaluate_mastery` -> `MasteryEvaluationGraph`
  - `fallback` -> 安全澄清或兜底响应
- 约束：Orchestrator 的路由审计属于 `audit_events`，不应写成业务 `LearningEvent`。

### QAGraph

- 输入：用户问题、学习上下文、`source_policy`、可用 tool capability、可选历史学习信号摘要。
- 输出：`FinalResponse`、`EvidenceChunk`、`ToolResult`、`LearningEvent`。
- 约束：只写 `LearningEventRepository`，不写题目、attempt 或 mastery。

### QuestionGenerationGraph

- 输入：目标概念、题型、难度、数量、source policy、可选 mastery/attempt 摘要、可用证据。
- 输出：`QuestionItem`、`quality_report`、`FinalResponse`、`LearningEvent`。
- 约束：只写 `QuestionItemRepository` 和生成事件，不写 mastery。

### MasteryEvaluationGraph

- 输入：`LearningEvent`、attempt payload、历史 mastery snapshot、先修知识关系。
- 输出：`mastery_snapshots`、弱信号、下一步建议、`FinalResponse`。
- 约束：它是唯一允许写 `mastery_snapshots` 的业务 Graph。

## LearningEvent event_type 清单

### QAGraph 产生事件

- `question_answered`：每轮问答完成。payload 包含 `question_type`、`source_level`、`source_policy`、`answer_mode`、`evidence_refs`、`tool_result_refs`、`degraded`。
- `concept_explained`：讲解了一个主要概念。payload 包含 `concept_id/name/confidence`、`source_level`、`evidence_refs`。
- `evidence_used`：最终回答真正引用证据。payload 包含 `evidence_id`、`source_type`、`score`、`grounding_status`。
- `tool_fallback_used`：资料不足或低置信时使用工具 fallback。payload 包含 `capability`、`provider`、`tool_result_id`。
- `insufficient_evidence`：`notebook_only` 或 strict notebook 资料不足。payload 说明缺失主题和 source policy。
- `answer_repaired`：answer guard / repair 修改了低质量回答。

### QuestionGenerationGraph 产生事件

- `question_generated`：题目通过质量门并持久化。payload 包含 `question_item_id`、concept、difficulty、source_refs、generation_source。
- `question_reviewed`：题目质量审查结果。payload 包含 `passed`、issues、solver verifier、reviewer、retry_count。
- `question_generation_degraded`：出题流程降级但仍有可用输出。
- `question_generation_failed`：出题失败且没有持久化题目。

### MasteryEvaluationGraph 消费事件

- 强信号：
  - `practice_attempt_submitted`
  - `attempt_scored`
  - 可验证的 `question_answered`
- 中信号：
  - rubric/LLM 评分的 `question_answered`
  - 部分正确或低置信短答结果
- 弱信号：
  - `concept_explained`
  - `evidence_used`
  - `tool_fallback_used`
  - `insufficient_evidence`
  - `answer_repaired`
- 非 mastery 信号：
  - `question_generated`
  - `question_reviewed`
  - `question_generation_degraded`
  - `question_generation_failed`

`mastery_updated`、`next_step_recommended` 可以作为 MasteryEvaluationGraph 的输出审计事件，但不能再次作为 mastery 输入消费，避免循环。

## Repository 读写边界

| Graph | 可读 | 可写 | 禁止 |
| --- | --- | --- | --- |
| LearningOrchestratorGraph | 用户上下文、路由上下文 | `GraphRunRepository.record_audit_event` | 题目、attempt、mastery 事实写入 |
| QAGraph | Notebook chunks、学习摘要、工具结果 | `LearningEventRepository.append` | `MasterySnapshotRepository`、`QuestionItemRepository`、`AttemptRepository` |
| QuestionGenerationGraph | Notebook chunks、历史 attempts 摘要、mastery 摘要、相似题 | `QuestionItemRepository.create_question_item`、`LearningEventRepository.append` | `MasterySnapshotRepository`、`record_attempt`、`record_exposure` |
| MasteryEvaluationGraph | `LearningEventRepository`、`AttemptRepository`、历史 mastery | `MasterySnapshotRepository.upsert_snapshot` | 生成题目正文、生成完整教学回答 |

## ToolCapability 边界

### QAGraph

- 允许：`notebook_retrieve`、`web_search`、`web_extract`、`code_execute`。
- 暂不建议：`sql_read`、`file_parse`。
- 必须通过 `ToolExecutor` 和 `ToolPolicyResolver`。
- 禁止业务节点直接 import Tavily provider。

### QuestionGenerationGraph

- 允许：`notebook_retrieve`、必要时 `web_search` / `web_extract`。
- 题目相似度和持久化去重应通过 repository，不通过 Graph State 保存长期事实。
- 禁止为了出题直接更新 mastery。

### MasteryEvaluationGraph

- 默认不需要外部 web 工具。
- 可以读 attempts、learning events、mastery snapshots、concept/prerequisite 数据。
- 如果未来使用 `sql_read`，必须是只读 repository adapter，不暴露任意 SQL 给模型。

## source_policy 边界

- `notebook_only`：
  - 只允许 `notebook_retrieve`。
  - 禁止 `web_search`、`web_extract`、外部 provider。
  - QAGraph 资料不足时应产生 `insufficient_evidence`，不能编造。
- `notebook_plus_external`：
  - 允许 Notebook 和外部只读资料。
  - 外部工具仍需通过 policy resolver。
- `open_tools`：
  - 允许 capability 白名单内工具。
  - 仍禁止未注册 provider 和 Graph 节点直接 import provider。

## Orchestrator 路由关系

```text
request_guard
  -> load_runtime_context
  -> load_learner_context
  -> intent_router
  -> qa | generate_question | evaluate_mastery | fallback
  -> response_composer
  -> persist_audit_event
```

Orchestrator 不生成教学回答、不生成题目、不更新 mastery。子 Graph 应返回 `FinalResponse`，Orchestrator 只追加路由 UI metadata 和审计信息，不应压扁子图的 `concepts`、`evidence_refs`、`coach_actions`、`mastery_signals`。

## 禁止行为清单

- 禁止重新引入旧 graph/workflow/shadow/fallback 作为 `/api/chat` 生产路径。
- 禁止把 `learning_assistant` 兼容导出重新指向旧单体 graph。
- Graph-era schema 变更必须通过 Alembic migration。
- 禁止把 DB connection、LLM client、tool instance 放进 Graph State。
- 禁止把长期业务事实只存在 LangGraph checkpoint。
- 禁止 QAGraph 或 QuestionGenerationGraph 写 `mastery_snapshots`。
- 禁止业务 Graph 节点直接 import Tavily provider。
- 禁止把 `raw_retrieved_docs` 直接转成最终 `EvidenceChunk`。
- 禁止无限 retry / repair loop。
- `make eval-graphs` 默认只能声称完成本地 deterministic eval；真实 LangSmith dataset/evaluator 需要单独说明配置与执行结果。
