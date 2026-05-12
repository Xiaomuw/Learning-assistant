# 项目达标审查文档

> 目标读者：用于交给 Pro 模型或工程审查者，检查当前项目在问答、做题、中心编排、学习中心、掌握度、持久化和测试覆盖上是否达标。
>
> 口径说明：本文中的“中心模块”同时包含两部分：一是 `LearningOrchestratorGraph` 中心编排层，二是前端 `/dashboard` 对应的学习中心读模型。

## 1. 审查摘要

当前项目是 `FastAPI + LangGraph + LangChain + PostgreSQL/PGVector + Next.js` 架构。后端生产聊天入口已经从旧单体 graph/workflow 迁移到新的 `LearningOrchestratorGraph`，`/api/chat` 和 `/api/chat/sync` 公开协议保持兼容，但内部默认通过 Orchestrator 路由到独立业务 Graph。

当前新 Graph 体系的核心边界如下：

| 模块 | 职责 | 关键代码 | 主要输出 |
| --- | --- | --- | --- |
| `LearningOrchestratorGraph` | 请求守卫、上下文加载、意图路由、子图调用、响应组合、审计 | `backend/app/orchestration/graphs/orchestrator/` | `FinalResponse`、`response_envelope`、`audit_events` |
| `QAGraph` | 问答、证据检索、证据判断、工具 fallback、回答质量检查、学习事件 | `backend/app/orchestration/graphs/qa/` | `FinalResponse`、`EvidenceChunk`、`ToolResult`、`LearningEvent` |
| `QuestionGenerationGraph` | 出题蓝图、候选题生成、solver 校验、质量门、去重、题目持久化 | `backend/app/orchestration/graphs/question_generation/` | `QuestionItem`、`QualityReport`、`LearningEvent` |
| `MasteryEvaluationGraph` | 消费答题和学习事件、更新掌握度、生成下一步建议 | `backend/app/orchestration/graphs/mastery/` | `mastery_snapshots`、`mastery_updates`、`next_learning_actions` |
| 学习中心 | 聚合 taxonomy、掌握度、答题记录和题库数量，给前端展示学习进度 | `backend/app/domains/learning_center/service.py`、`frontend/app/dashboard/page.tsx` | 学科/章节/主题/知识点树、汇总指标、下一步建议 |

建议 Pro 审查时重点验证：

1. `/api/chat` 是否只通过 `LearningOrchestratorGraph` 进入生产链路。
2. `QAGraph` 和 `QuestionGenerationGraph` 是否不直接写 `mastery_snapshots`。
3. 业务 Graph 是否只通过 `ToolCapability` 和 `ToolExecutor` 使用工具，不直接 import Tavily provider。
4. `LearningEvent` 是否作为跨图学习信号，而非路由审计。
5. graph-era facts 表是否由 Alembic 管理，生产 schema 变更是否有 migration。
6. 学习中心是否读取 graph-era mastery/attempt/question facts，而不是依赖 LangGraph checkpoint 保存长期事实。

## 2. 项目总览

### 2.1 技术栈

- 后端 API：`FastAPI`，主要接口位于 `backend/app/interfaces/api/`。
- Graph 编排：`LangGraph`，新企业级 Graph 位于 `backend/app/orchestration/graphs/`。
- LLM 与工具：`LangChain` 及项目内 `domains.qa.runtime`、`services.tooling`。
- 数据层：`PostgreSQL/PGVector`，graph-era facts 由 SQLAlchemy model 和 Alembic migration 管理。
- 前端：`Next.js`，核心页面位于 `frontend/app/`，API 封装位于 `frontend/lib/api.ts`。

### 2.2 生产入口现状

生产聊天入口由以下链路承接：

```text
POST /api/chat 或 POST /api/chat/sync
  -> backend/app/interfaces/api/chat.py
  -> backend/app/application/chat/service.py
  -> backend/app/application/chat/orchestrator_runtime.py
  -> LearningOrchestratorGraph
```

`backend/app/application/chat/orchestrator_runtime.py` 中的 `run_orchestrator_chat()` 和 `stream_orchestrator_chat()` 负责：

- 构造 Orchestrator 输入 state。
- 创建 graph facts repository。
- 调用 `build_orchestrator_graph(...).compile().invoke(...)` 或 stream。
- 将 `FinalResponse` 和 `response_envelope` 映射回当前兼容的 `ChatResponse / SSE` 结构。
- 记录 LangSmith trace 名称：`chat.orchestrator.sync`、`chat.orchestrator.sse`。
- 写入 graph run、child facts、审计摘要。

`backend/langgraph.json` 继续保留外部兼容 key `learning_assistant`，但根据 `docs/agent-graphs/status.md`，它导出的 compiled graph 已指向新的 Orchestrator，而不是旧单体生产图。

### 2.3 已废弃边界

根据 `docs/agent-graphs/status.md` 和当前代码结构，旧生产入口已经废弃：

- 不再走旧 `backend/app/orchestration/graph/`。
- 不再走旧 `backend/app/orchestration/workflow/`。
- 不再保留 chat shadow、runtime selector、legacy fallback 映射。
- 旧领域服务如 `domains.qa`、`domains.practice`、`domains.mastery` 仍可复用，但必须通过新 Graph adapter 暴露 contract 输出。

## 3. 统一契约与跨图协议

统一契约事实源是：

```text
backend/app/shared/schemas/agent_graphs.py
```

### 3.1 核心 schema

| schema | 作用 | 关键字段 |
| --- | --- | --- |
| `GraphType` | 标识 graph 类型 | `orchestrator`、`qa`、`question_generation`、`mastery` |
| `SourcePolicy` | 控制资料与外部工具策略 | `notebook_only`、`notebook_plus_external`、`open_tools` |
| `ToolCapability` | 工具能力抽象 | `notebook_retrieve`、`web_search`、`web_extract`、`sql_read`、`code_execute`、`file_parse` |
| `EvidenceChunk` | 标准证据片段 | `source_type`、`source_id`、`text`、`score`、`concepts` |
| `ToolResult` | 标准工具结果 | `tool_id`、`provider`、`capability`、`status`、`evidence` |
| `LearningEvent` | 跨图学习信号 | `event_type`、`user_id`、`concept_id`、`graph_run_id`、`payload` |
| `FinalResponse` | 子图统一响应 | `answer`、`source_level`、`concepts`、`evidence_refs`、`coach_actions`、`mastery_signals`、`ui_payload` |
| `GraphError` | 结构化错误 | `code`、`message`、`node`、`severity`、`metadata` |

### 3.2 `LearningEventType` 边界

`LearningEventType` 在 `backend/app/shared/schemas/agent_graphs.py` 中定义，并被拆成几个白名单集合：

- `QA_LEARNING_EVENT_TYPES`
- `QUESTION_GENERATION_EVENT_TYPES`
- `MASTERY_CONSUMABLE_EVENT_TYPES`
- `MASTERY_OUTPUT_EVENT_TYPES`

这使 Pro 审查可以检查事件是否越界。例如：

- `QAGraph` 主要产生 `question_answered`、`concept_explained`、`evidence_used`、`tool_fallback_used`、`insufficient_evidence`、`answer_repaired`。
- `QuestionGenerationGraph` 主要产生 `question_generated`、`question_reviewed`、`question_generation_degraded`、`question_generation_failed`。
- `MasteryEvaluationGraph` 消费学习事件和 attempts，并输出 `mastery_updated`、`next_step_recommended`。

重要约束：Orchestrator 的路由审计不应写成业务 `LearningEvent`，应进入 `audit_events` 或 `GraphRunRepository.record_audit_event()`。

## 4. 中心编排模块：`LearningOrchestratorGraph`

### 4.1 入口与核心代码

关键实现：

```text
backend/app/application/chat/orchestrator_runtime.py
backend/app/orchestration/graphs/orchestrator/graph.py
backend/app/orchestration/graphs/orchestrator/nodes.py
backend/app/orchestration/graphs/orchestrator/intent_rules.py
backend/app/orchestration/graphs/orchestrator/router.py
backend/app/orchestration/graphs/orchestrator/child_invokers.py
```

Graph 构建入口是 `backend/app/orchestration/graphs/orchestrator/graph.py` 的 `build_graph()`。

### 4.2 节点流程

当前 Orchestrator 节点顺序为：

```text
request_guard
  -> load_runtime_context
  -> load_learner_context
  -> graph_router
  -> qa_graph | question_generation_graph | mastery_evaluation_graph | top_level_clarify_or_refuse
  -> persist_learning_events
  -> response_composer
  -> persist_audit_event
  -> END
```

职责拆分：

| 节点 | 职责 |
| --- | --- |
| `request_guard` | 初始化 run id、graph 类型、source policy、messages、errors，并拒绝空消息 |
| `load_runtime_context` | 注入可用 capability 列表和 graph version |
| `load_learner_context` | 注入 user、notebook、course、thread 等学习上下文 |
| `graph_router` | 调用 `resolve_intent_decision()` 识别 QA、出题、掌握度或 fallback |
| `qa_graph` | 通过 `QAGraphInvoker` 调用 `QAGraph` |
| `question_generation_graph` | 通过 `QuestionGenerationGraphInvoker` 调用 `QuestionGenerationGraph` |
| `mastery_evaluation_graph` | 通过 `MasteryEvaluationGraphInvoker` 调用 `MasteryEvaluationGraph` |
| `persist_learning_events` | 在 Orchestrator 边界持久化子图 learning events，失败时 fail-open |
| `response_composer` | 组合 `FinalResponse`、`response_envelope`、兼容 sync/SSE payload |
| `persist_audit_event` | 写入路由和子图调用审计，失败时 fail-open |

### 4.3 意图路由

意图规则在 `backend/app/orchestration/graphs/orchestrator/intent_rules.py`：

1. `RequestErrorIntentRule`：已有 request error 时进入 fallback。
2. `QuizGenerateIntentRule`：`QuizRequestResolver` 识别完整出题请求时进入 `QuestionGenerationGraph`。
3. `QuizClarifyIntentRule`：出题意图缺上下文时返回澄清面板。
4. `KeywordQuestionGenerationIntentRule`：命中“出题 / 练习题 / 刷题 / 生成题目”等关键词时进入出题图。
5. `MasteryIntentRule`：命中“掌握度 / 评估 / 评分 / 薄弱 / 学习状态”时进入掌握度图。
6. `HelpStatusIntentRule`：help/status 或问号进入 fallback。
7. `DefaultQAIntentRule`：默认学习问答。

最终 `route_after_intent()` 在 `backend/app/orchestration/graphs/orchestrator/router.py` 将 intent 映射到具体子图节点。

### 4.4 子图调用

`backend/app/orchestration/graphs/orchestrator/child_invokers.py` 定义三个 invoker：

- `QAGraphInvoker`
- `QuestionGenerationGraphInvoker`
- `MasteryEvaluationGraphInvoker`

它们负责：

- 建立子图 trace。
- 构造子图 state。
- 按 `production_runtime` 决定 deterministic graph 或 production graph。
- 将子图结果包装成 `ChildGraphResult` 和 `ChildGraphOutput`。
- 将错误转成结构化 `GraphError`，避免异常直接打断 Orchestrator。

### 4.5 响应兼容

Orchestrator 的 `_response_envelope()` 会把子图输出映射成当前前端需要的兼容结构：

- `explanation`
- `quiz`
- `memory`
- `final`
- `sse_events`
- `sync_payload`

当子图为 `QuestionGenerationGraph` 时，`quiz.items / quiz_request / quiz_clarification / quiz_generation_status` 会被放入响应，保证 `/api/chat` 旧问答 shape 与新增出题字段可以共存。

### 4.6 审查结论

从当前代码看，Orchestrator 符合“只负责路由、上下文加载、响应组合、审计”的边界。它不直接生成教学回答、不直接生成题目、不直接更新 mastery。需要 Pro 重点复核的是：后续改动是否仍保持这个边界，尤其不要在 Orchestrator node 中重新堆业务逻辑或直接写领域事实。

## 5. 问答模块：`QAGraph`

### 5.1 入口与核心代码

关键实现：

```text
backend/app/orchestration/graphs/qa/graph.py
backend/app/orchestration/graphs/qa/nodes.py
backend/app/orchestration/graphs/qa/adapter.py
backend/app/domains/qa/runtime.py
backend/app/domains/qa/tool_loop.py
backend/app/domains/qa/capability_tools.py
backend/app/services/tooling/
```

生产链路：

```text
/api/chat
  -> run_orchestrator_chat()
  -> LearningOrchestratorGraph
  -> QAGraphInvoker
  -> QAGraph
  -> ProductionQARuntimeAdapter
  -> domains.qa.runtime.create_agent(...).run()
```

### 5.2 QAGraph 节点流程

`backend/app/orchestration/graphs/qa/graph.py` 当前节点顺序为：

```text
input_normalize
  -> qa_intent_classifier
  -> context_resolver
  -> concept_linker
  -> knowledge_router
  -> internal_retrieval
  -> evidence_judge
  -> web_search_if_needed 或 evidence_merge
  -> evidence_merge
  -> answer_generate
  -> answer_quality_check
  -> answer_repair 或 qa_clarification_response 或 qa_result_compose
  -> compose_learning_events
  -> END
```

### 5.3 关键过程

#### 输入规范化

`input_normalize_node()` 做以下事情：

- 标准化用户问题。
- 推断 `question_type`。
- 设置 `source_policy`。
- 初始化 `qa_request`。
- 初始化 repair 计数，默认 `MAX_ANSWER_REPAIR_ATTEMPTS = 1`。

#### 概念绑定

`concept_linker_node()` 通过 `get_concept_registry().match_query()` 把问题映射到 408 taxonomy 中的概念、主题、学科。若匹配成功，会追加 `ConceptRef`。

#### 知识库路由

`knowledge_router_node()` 选择检索目标：

- 当前 notebook。
- 当前 course。
- 显式命名知识库。
- concept registry 对应 subject。
- 最多保留 `MAX_KNOWLEDGE_ROUTES = 3`。

#### 内部证据检索

`internal_retrieval_node()` 不直接 import provider，而是构造 `ToolExecutionRequest`：

- capability 为 `ToolCapability.NOTEBOOK_RETRIEVE`。
- 通过 `ToolExecutor` 执行。
- 结果统一为 `ToolResult`，其 `evidence` 转成 `EvidenceChunk`。

如果没有 executor，则只规划 `tool_requests`，不会实际调用外部工具。

#### 证据判断与 web fallback

`evidence_judge_node()` 判断 notebook/course 证据是否足够：

- `PARTIAL_EVIDENCE_SCORE = 0.55`
- `STRONG_EVIDENCE_SCORE = 0.70`
- 输出 `evidence_gate` 和 `evidence_judgement`

`route_after_evidence_judge()` 只有在证据不足且策略允许时才进入 `web_search_if_needed_node()`。

`web_search_if_needed_node()` 使用 `ToolCapability.WEB_SEARCH`，且受 `source_policy` 控制：

- `notebook_only`：禁止 web。
- `notebook_plus_external`：内部证据不足且有外部搜索信号时允许。
- `open_tools`：在 capability 白名单内允许。

#### 回答生成

`answer_generate_node()` 调用 `run_adapter()`。生产模式下 adapter 是 `ProductionQARuntimeAdapter`，它会把 graph contract 映射成 `AgentRequest`，再调用 `domains.qa.runtime.create_agent(...).run()`。

`ProductionQARuntimeAdapter` 的职责是：

- 把 `EvidenceChunk` 转成 runtime docs。
- 设置 `rag_precomputed`、`notebook_context`、`context_audit`。
- 注入 `source_policy`、`notebook_policy`、`allow_tools`、`allow_search`。
- 把旧 runtime 输出重新收敛为 `FinalResponse`、`ToolResult`、`LearningEvent`、`GraphError`、`runtime_summary`。

#### 回答质量检查与 repair

`answer_quality_check_node()` 检查：

- 是否空回答。
- `evidence_refs` 是否存在。
- 时效/来源类问题是否缺 web。
- `notebook_only` 是否在没有 notebook evidence 时声称 notebook 来源。

repair 路径有限：

- 可修复问题进入 `answer_repair_node()`。
- 不能修复或策略冲突进入 `qa_clarification_response_node()`。
- 不存在无限 retry。

#### 学习事件

`compose_learning_events()` 生成：

- `question_answered`
- `insufficient_evidence`
- `answer_repaired`
- `concept_explained`
- `evidence_used`
- `tool_fallback_used`

该节点只返回 state 中的 `learning_events`。QAGraph 本身不会直接写 mastery、question item、attempt。持久化在 Orchestrator 或注入 repository 边界完成。

### 5.4 工具边界

问答工具抽象通过：

```text
backend/app/services/tooling/executor.py
backend/app/services/tooling/policy.py
backend/app/services/tooling/registry.py
backend/app/services/tooling/adapters/
```

审查重点：

- Graph 节点请求 `ToolCapability`，不请求具体 provider。
- Tavily 等 provider 应只存在于 adapter/registry 兼容层。
- `ToolPolicyResolver` 应继续限制 `source_policy x capability`。

### 5.5 审查结论

QAGraph 当前满足“问答、证据判断、工具 fallback、grounding、LearningEvent”的边界。需要关注的风险是旧 `domains.qa.runtime` 内部仍保留复杂 tool loop 和 fallback 逻辑，Pro 应检查它通过 adapter 输出时是否没有泄漏旧 provider 名、raw docs、完整 prompt 或未审查证据。

## 6. 做题模块：出题与答题

做题模块有两条入口：

1. 聊天中输入“帮我出题 / 再来几道 / 考我一下”等，由 Orchestrator 路由到 `QuestionGenerationGraph`。
2. 刷题页或 API 直接请求 `POST /api/practice/packs` 生成题包，提交答案走 `POST /api/practice/attempts`。

### 6.1 出题意图解析

关键代码：

```text
backend/app/domains/practice/quiz_request.py
backend/app/orchestration/graphs/orchestrator/intent_rules.py
```

`resolve_quiz_request()` 会输出稳定的 `QuizRequestResolution`，包含：

- `action`：`generate_practice_pack`、`clarify_quiz_request`、`continue_practice`、`normal_qa`
- `intent`
- `topic`
- `subject_id`
- `question_type`
- `difficulty`
- `count`
- `need_clarification`
- `recommended_options`

Orchestrator 在路由前解析出题意图：

- 信息完整：进入 `QuestionGenerationGraph`。
- 缺主题或方向：返回 `QuizClarificationPanel`。
- 普通问题：继续进入 `QAGraph`。

### 6.2 `QuestionGenerationGraph` 核心代码

关键实现：

```text
backend/app/orchestration/graphs/question_generation/graph.py
backend/app/orchestration/graphs/question_generation/nodes.py
backend/app/orchestration/graphs/question_generation/schemas.py
backend/app/orchestration/graphs/question_generation/adapter.py
backend/app/application/practice/pack_service.py
```

Graph 节点顺序：

```text
build_blueprint
  -> prepare_source_refs
  -> generate_candidates
  -> solver_verifier
  -> quality_reviewer
  -> repair_candidates 或 dedupe_checker
  -> difficulty_calibrator
  -> persist_question_items
  -> compose_response
  -> END
```

### 6.3 出题 schema

`backend/app/orchestration/graphs/question_generation/schemas.py` 定义：

- `SourceRef`：来源引用。
- `AnswerOption`：A/B/C/D 选项。
- `AnswerKey`：正确选项、正确选项文本、标准解析、每个选项的 rationale。
- `Rubric`：评分标准、满分条件、常见误区。
- `ItemBlueprint`：概念、难度、题型、数量、source policy。
- `QuestionCandidate`：候选题。
- `QualityReport`：质量检查结果。
- `QuestionItem`：最终持久化题目。

### 6.4 候选题生成

adapter 层包括：

- `DeterministicQuestionCandidateGenerator`：测试安全的确定性生成器。
- `LegacyPracticeQuestionCandidateGenerator`：包装旧 `domains.practice.generation`。
- `QuestionCandidateRepairer`：质量失败后的有限修复入口。

生产刷题补题入口 `PracticePackService` 会构造 `LegacyPracticeQuestionCandidateGenerator`，再调用 `build_production_graph(candidate_generator=generator)`。

### 6.5 质量门

`quality_reviewer_node()` 检查：

- 题目数量是否满足 blueprint count。
- 每题是否有 `source_refs`。
- `primary_concept_id` 是否匹配。
- 是否有完整 `option_rationales`。
- 是否有标准解析。
- 是否有 rubric。
- `notebook_only` 下是否 grounding 到 notebook。
- 主题是否和请求概念一致。
- 包内是否重复。

`solver_verifier_node()` 检查：

- 选项是否完整 A/B/C/D。
- 正确答案是否在选项中。
- 选项文本是否重复。
- `correct_option_text` 是否和正确选项文本一致。

`difficulty_calibrator_node()` 检查候选题难度是否匹配请求难度。

有限 repair 通过 `route_after_quality_reviewer()` 控制，默认不会无限重试。

### 6.6 去重与持久化

`make_dedupe_checker_node()` 通过 `QuestionItemRepository.find_similar()` 查相似题。如果发现重复题，会复用已有 question id，而不是重复创建。

`make_persist_question_items_node()` 在质量通过时：

- 调用 `QuestionItemRepository.create_question_item()`。
- 生成 `question_generated` 事件。
- 生成 `question_reviewed` 事件。
- 如果降级但仍可用，生成 `question_generation_degraded`。

质量失败时：

- 不保存题目。
- 生成 `question_generation_failed`。

### 6.7 刷题页题包接口

关键代码：

```text
backend/app/interfaces/api/practice.py
backend/app/application/practice/pack_service.py
frontend/app/practice/page.tsx
frontend/lib/api.ts
```

`POST /api/practice/packs`：

- 校验当前用户只能给自己生成题包。
- 根据当前题、上一组题、前端 context 构造 resolver context。
- 如果可以从当前题上下文识别 canonical concept，则直接生成该概念题包。
- 如果缺少主题，则返回 clarification。
- 通过 `QuestionGenerationGraph` 生成题包。
- 将 `QuestionItem` 转为前端兼容的 `PracticeRecommendation`。

### 6.8 提交答案接口

关键代码：

```text
backend/app/interfaces/api/practice.py
backend/app/application/practice/service.py
backend/app/domains/practice/attempts.py
backend/app/domains/mastery/evaluation.py
backend/app/application/practice/graph_facts.py
```

`POST /api/practice/attempts` 过程：

1. 接口层校验 user 权限、题干、A/B/C/D 选项、正确答案。
2. `submit_attempt()` 调用 `record_practice_attempt_immediate()` 立即保存 legacy attempt 并返回 queued 结果。
3. 后台任务 `finalize_attempt_analysis()` 执行掌握度分析、记忆更新和 graph-era mastery 更新。
4. `_finalize_practice_attempt_analysis()` 调用 `evaluate_practice_answer()`。
5. `evaluate_practice_answer()` 做答案规范化、RAG 参考检索、维度打分、掌握等级判断，并调用 `record_attempt()` 更新 legacy knowledge stats。
6. `update_graph_mastery_from_practice_attempt()` 在 graph facts 开启时写 graph attempt，并调用 `MasteryEvaluationGraph` 更新 `mastery_snapshots`。

### 6.9 双写与事件

`backend/app/application/practice/graph_facts.py` 中：

- `maybe_dual_write_practice_attempt()` 受 `ENABLE_GRAPH_DUAL_WRITE` 和 `ENABLE_GRAPH_FACTS` 控制。
- `_dual_write_practice_attempt()` 会写：
  - `practice_attempt_submitted`
  - `attempt_scored`
  - graph-era `attempts`
  - graph run audit
  - 调用 `MasteryEvaluationGraph`

这些写入 fail-open，不影响用户看到的判题结果。

### 6.10 审查结论

做题模块当前覆盖了“出题”和“答题”两阶段。出题已进入 `QuestionGenerationGraph` 质量门和持久化边界；答题仍兼容旧 practice attempts 和 memory，同时在 graph facts 开启时可写入 attempts 并触发 `MasteryEvaluationGraph`。Pro 应重点检查当前未提交改动是否影响后台 finalizer、duplicate submission、graph dual-write 和 mastery 更新顺序。

## 7. 掌握度模块：`MasteryEvaluationGraph`

### 7.1 入口与核心代码

关键实现：

```text
backend/app/orchestration/graphs/mastery/graph.py
backend/app/orchestration/graphs/mastery/nodes.py
backend/app/orchestration/graphs/mastery/schemas.py
backend/app/domains/mastery/evaluation.py
backend/app/domains/mastery/service.py
backend/app/application/practice/graph_facts.py
```

入口来源：

- Orchestrator 路由到 `MasteryEvaluationGraph`。
- Practice API 后台 finalizer 调用 `update_graph_mastery_from_practice_attempt()`。
- graph facts dual-write 后调用 `build_mastery_graph(...).compile().invoke(...)`。
- 也可通过 repository load 消费历史 `learning_events` 和 `attempts`。

### 7.2 Graph 节点流程

`backend/app/orchestration/graphs/mastery/graph.py` 节点顺序：

```text
load_repository_inputs
  -> objective_grader
  -> weak_signal_extractor
  -> evidence_aggregator
  -> mastery_updater
  -> status_classifier
  -> persist_snapshots
  -> next_action_policy
  -> response_composer
  -> END
```

### 7.3 信号分类

`backend/app/orchestration/graphs/mastery/nodes.py` 中：

- strong signals：
  - `practice_attempt_submitted`
  - `attempt_scored`
  - 可验证的 `question_answered`
- weak signals：
  - `concept_explained`
  - `evidence_used`
  - `tool_fallback_used`
  - `insufficient_evidence`
  - `answer_repaired`
  - `misconception_detected`
  - `hint_requested`
  - `stuck_reported`

弱信号不能覆盖强信号：`evidence_aggregator_node()` 在同一 concept 有 strong/medium evidence 时忽略 weak evidence。

### 7.4 bounded update

`mastery_updater_node()` 使用历史 mastery 作为 previous，按 evidence strength、confidence、observed score 计算 delta：

- strong cap：`0.18`
- medium cap：`0.10`
- weak cap：`0.03`
- 最终 `p_mastery` 被限制在 `[0.0, 1.0]`
- 使用 hint 时正向 delta 会降权

`status_classifier_node()` 根据 `p_mastery` 分类：

- `>= 0.8`：`mastered`
- `>= 0.5`：`learning`
- `< 0.5`：`weak`

### 7.5 持久化边界

只有 `MasteryEvaluationGraph` 允许写 `MasterySnapshotRepository.upsert_snapshot()`。

`build_production_graph()` 在 graph facts 开启时使用：

- `LearningEventRepository`
- `CompositeAttemptRepository`
- `CompositeMasterySnapshotRepository`

graph facts 关闭时，使用 legacy read/write adapter：

- `LegacyPracticeAttemptRepository`
- `LegacyKnowledgeStatsMasteryRepository`

### 7.6 下一步建议

`next_action_policy_node()` 根据 status 输出：

- `mastered`：`advance`
- `learning`：`practice_variant`
- `weak`：`review_prerequisite`

`response_composer_node()` 生成：

- `mastery_updated`
- `next_step_recommended`
- `FinalResponse.mastery_signals`

### 7.7 审查结论

掌握度模块符合“消费 LearningEvent / attempts 并更新 mastery”的边界。Pro 需要重点检查幂等性：同一个 `LearningEvent.id` 或 `attempt_id` 不应重复消费，`consumed_signal_ids` 应随 snapshot 输出保留。

## 8. 学习中心模块：`/dashboard`

### 8.1 后端入口与核心代码

关键实现：

```text
backend/app/interfaces/api/user_data.py
backend/app/application/user_data/service.py
backend/app/domains/learning_center/service.py
backend/app/shared/schemas/contracts.py
frontend/app/dashboard/page.tsx
frontend/lib/api.ts
```

API：

```text
GET /api/users/{user_id}/learning-center?subject_id=...
```

接口层位于 `backend/app/interfaces/api/user_data.py`：

- 使用 `verify_user_access`。
- response model 为 `LearningCenterResponse`。
- 调用 application service `get_learning_center_service()`。

application 层位于 `backend/app/application/user_data/service.py`：

- 调用 `domains.learning_center.service.get_learning_center()`。
- 使用 `LearningCenterResponse.model_validate(...)` 做契约校验。

### 8.2 后端聚合逻辑

`backend/app/domains/learning_center/service.py` 的 `get_learning_center()` 聚合四类数据：

1. taxonomy：
   - `_taxonomy_from_registry()`
   - `_taxonomy_from_db()`
   - `_merged_taxonomy()`
2. mastery snapshots：
   - `_snapshots_by_concept()`
   - 来源表：`mastery_snapshots`
3. attempts：
   - `_attempt_stats_by_concept()`
   - 来源表：graph-era `attempts`
4. question counts：
   - `_question_counts_by_concept()`
   - 来源表：`practice_questions`

随后 `_build_subjects()` 构造层级：

```text
subject
  -> chapter
  -> topic
  -> concept
```

每个 concept 包含：

- `p_mastery`
- `mastery_score`
- `status`
- `tested`
- `attempt_count`
- `correct_count`
- `wrong_count`
- `question_count`
- `last_practiced_at`
- `updated_at`

每个 topic/chapter/subject 通过 `_aggregate_concepts()` 和 `_aggregate_nodes()` 计算：

- `concept_count`
- `mastery_score`
- `coverage_ratio`
- `status_counts`
- `weak_count`
- `tested_count`
- `untested_count`
- `tested_ratio`
- `attempt_count`
- `correct_count`
- `wrong_count`

### 8.3 下一步建议

`_choose_next_move()` 的优先级：

1. 已练过且仍薄弱的概念：`review_and_practice`
2. 学习中的概念：`practice_variant`
3. 高频或高重要度未开始概念：`start_high_value_concept`
4. 默认继续第一个概念：`continue_learning`

输出 `LearningCenterNextMove`，前端用于推荐下一步动作。

### 8.4 前端展示

`frontend/app/dashboard/page.tsx` 通过 `fetchLearningCenter(userId)` 获取数据，并展示：

- 四科架构总览。
- 知识点数、已测数、薄弱点、练习数。
- 正确/错误统计。
- 下一步建议。
- 学科、章节、主题、知识点可展开树。
- 每个知识点的掌握进度、题库数量、练习次数、正确/错误次数。
- 跳转到问答页和刷题页。

`frontend/lib/api.ts` 定义了前端契约：

- `LearningCenterStatus`
- `LearningCenterConcept`
- `LearningCenterTopic`
- `LearningCenterChapter`
- `LearningCenterSubject`
- `LearningCenterNextMove`
- `LearningCenterResponse`
- `fetchLearningCenter()`

### 8.5 审查结论

学习中心是读模型，不直接改变 Graph state。它读取 taxonomy、mastery snapshots、attempts 和题库数量，适合作为项目达标审查中的“中心展示模块”。Pro 应检查其聚合是否只读、是否能处理空 taxonomy、空 snapshot、空 attempts，以及前端是否能在 subject 缺失时安全展示空状态。

## 9. 持久化、迁移与 Repository 边界

### 9.1 Repository Protocol

事实源：

```text
backend/app/persistence/interfaces.py
```

核心 Protocol：

- `GraphRunRepository`
- `LearningEventRepository`
- `ToolRunRepository`
- `QuestionItemRepository`
- `AttemptRepository`
- `MasterySnapshotRepository`
- `NotebookChunkRepository`
- `ConceptRepository`

业务 Graph 只依赖 Protocol，不应持有 SQLAlchemy session、数据库连接、LLM client 或 tool instance。

### 9.2 SQL repository

SQL 实现：

```text
backend/app/persistence/repositories/graph_facts.py
```

`build_graph_fact_repositories()` 返回：

- `SqlGraphRunRepository`
- `SqlLearningEventRepository`
- `SqlToolRunRepository`
- `SqlAttemptRepository`
- `SqlMasterySnapshotRepository`
- `SqlQuestionItemRepository`
- `SqlConceptRepository`

并包装为 `GraphFactRepositories`。

### 9.3 graph-era facts 表

SQLAlchemy model 位于：

```text
backend/app/infrastructure/db/models.py
```

主要表：

| 表 | 作用 |
| --- | --- |
| `graph_runs` | Graph run 审计、状态、输入输出摘要、LangSmith 对齐字段 |
| `node_runs` | 节点级审计事件 |
| `tool_runs` | 工具调用审计，只保存 capability/provider/status/摘要 |
| `learning_events` | 跨图学习事件 |
| `attempts` | graph-era 答题记录 |
| `mastery_snapshots` | 用户概念掌握度快照 |
| `question_items` | graph-era 题目 |
| `concepts` | graph-era 概念 |

### 9.4 Alembic migration

基础 migration：

```text
backend/alembic/versions/0001_graph_facts.py
```

它创建：

- `graph_runs`
- `node_runs`
- `tool_runs`
- `learning_events`
- `attempts`
- `mastery_snapshots`
- `question_items`
- `concepts`

并创建关键索引。

LearningEvent 幂等 migration：

```text
backend/alembic/versions/0007_learning_event_idempotency.py
```

它为 `learning_events` 增加：

- `hash_key`
- `ix_learning_events_hash_key`
- `uq_learning_events_hash_key`

`SqlLearningEventRepository.append()` 会使用 payload 中的 `hash_key` 避免重复写入。

### 9.5 长期事实边界

当前架构意图明确：

- PostgreSQL domain tables 是长期业务事实来源。
- LangGraph checkpoint 只用于运行恢复、短期状态和线程续跑。
- 不把长期业务事实只存入 checkpoint。
- Graph State 只保存可 JSON 序列化数据。

### 9.6 审查结论

持久化层符合 repository-first 的边界。Pro 应检查新增 schema 变更是否都通过 Alembic migration，不要用 `Base.metadata.create_all()` 作为生产 schema 管理方式，也不要让业务 Graph 直接操作 SQLAlchemy session。

## 10. 前端协作

### 10.1 API 契约

前端 API 封装位于：

```text
frontend/lib/api.ts
```

该文件定义：

- 问答相关类型和 SSE 请求。
- `QuizItem`、`PracticeRecommendationPayload`、`PracticeAttemptResult`。
- `QuizRequestResolution`、`QuizClarificationPanel`。
- `LearningCenterResponse` 及其子结构。
- `fetchLearningCenter()`、practice pack、practice attempt 等 API 函数。

### 10.2 页面职责

| 页面 | 作用 | 后端对应 |
| --- | --- | --- |
| `frontend/app/chat/page.tsx` | 问答、聊天出题、SSE 展示 | `/api/chat`、Orchestrator、QAGraph、QuestionGenerationGraph |
| `frontend/app/practice/page.tsx` | 题包展示、作答、AI 补题 | `/api/practice/packs`、`/api/practice/attempts` |
| `frontend/app/dashboard/page.tsx` | 学习中心、知识树、下一步建议 | `/api/users/{user_id}/learning-center` |

### 10.3 前端审查重点

- `frontend/lib/api.ts` 的类型是否和后端 response model 对齐。
- `/chat` 是否能处理新增 `quiz_request / quiz_clarification / quiz_generation_status`。
- `/practice` 是否能处理 queued/completed/duplicate 的 `analysis_status`。
- `/dashboard` 是否能处理空 subjects、加载失败、无 next move。
- 触及前端或共享接口后必须重新运行 `npm run lint` 和 `npm run build`。

## 11. 达标检查矩阵

| 检查项 | 当前状态 | 证据代码位置 | Pro 审查重点 |
| --- | --- | --- | --- |
| `/api/chat` 生产入口走 Orchestrator | 已满足 | `backend/app/application/chat/orchestrator_runtime.py` | 确认没有恢复旧 graph/workflow fallback |
| Orchestrator 只编排不执行业务 | 已满足 | `backend/app/orchestration/graphs/orchestrator/` | 子图业务逻辑不要回流到 Orchestrator node |
| QAGraph 输出 `FinalResponse + LearningEvent` | 已满足 | `backend/app/orchestration/graphs/qa/` | `EvidenceChunk` 是否只来自审核后证据 |
| QAGraph 不写 mastery/question/attempt | 已满足 | `backend/tests/test_cross_graph_contracts.py`、`backend/tests/test_qa_graph_adapter.py` | 后续改动不能新增 repository 越界 |
| 工具通过 capability | 已满足 | `backend/app/services/tooling/`、`qa/nodes.py` | 业务 Graph 不直接 import Tavily provider |
| `notebook_only` 阻止 web | 已满足 | `qa/nodes.py`、`tooling/policy.py` | 检查 web fallback 条件 |
| 出题图有质量门 | 已满足 | `question_generation/nodes.py` | 检查 solver、rubric、source refs、dedupe、difficulty |
| 出题图不写 mastery | 已满足 | `question_generation/graph.py`、contract tests | 不允许生成题时直接改掌握度 |
| Practice API 提交答题 | 已满足 | `interfaces/api/practice.py`、`domains/practice/attempts.py` | 后台 finalizer fail-open 是否安全 |
| MasteryGraph 唯一写 `mastery_snapshots` | 已满足 | `mastery/graph.py`、`mastery/nodes.py` | 检查新写入路径是否绕过 MasteryGraph |
| 学习中心读取 graph-era facts | 已满足 | `domains/learning_center/service.py` | 空数据和 taxonomy 合并逻辑 |
| graph-era facts 由 Alembic 管理 | 已满足 | `backend/alembic/versions/0001_graph_facts.py` | 新 schema 不应无 migration |
| LearningEvent 幂等 | 已满足 | `0007_learning_event_idempotency.py`、`SqlLearningEventRepository` | `hash_key` 是否覆盖 fallback/重试场景 |
| 测试命令集中 | 已满足 | `Makefile` | 审查时应重新运行，不只引用历史结果 |
| `make eval-graphs` 语义清楚 | 已满足 | `Makefile`、`docs/agent-graphs/status.md` | 只能称本地 deterministic eval，不声称远程 LangSmith 通过 |

## 12. 测试与验证命令

建议 Pro 模型或工程审查者在当前工作树上重新运行：

```bash
make test-graphs
make eval-graphs
backend/.venv313/bin/python -m unittest discover -s backend/tests -t .
```

如果审查范围包含前端或共享接口，再运行：

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

如果前端 dev server 正在运行，执行 `npm run build` 后必须重启 dev server 再浏览器复测，避免 `.next` 缓存错位。

重要声明：

- `make eval-graphs` 当前是本地 deterministic graph smoke eval。
- 不要声称 LangSmith dataset/evaluator 真实远程 eval 已通过，除非显式运行了远程命令并记录环境、项目、dataset 和结果。
- `make eval-graphs-remote` 需要网络、LangSmith 配置和 `LANGSMITH_API_KEY`。

## 13. 建议 Pro 审查流程

1. 先读本文和 `docs/agent-graphs/status.md`，确认目标架构与当前状态。
2. 搜索旧生产入口是否残留：

```bash
rg -n "workflow_adapter|qagraph_shadow|graph_runtime|orchestration.workflow|orchestration.graph" backend/app
```

3. 搜索业务 Graph 是否越界写 repository：

```bash
rg -n "MasterySnapshotRepository|QuestionItemRepository|AttemptRepository|Tavily|tavily" backend/app/orchestration/graphs
```

4. 运行 `make test-graphs`。
5. 检查 `/api/chat`、`/api/practice/packs`、`/api/practice/attempts`、`/api/users/{user_id}/learning-center` 的接口契约。
6. 若涉及真实数据库，检查 Alembic head、graph-era facts 表和索引是否存在。
7. 若涉及前端，运行 lint/build 并手动复测 `/chat`、`/practice`、`/dashboard`。

## 14. 剩余风险与关注点

### 14.1 题目质量仍需要真实样本校准

`QuestionGenerationGraph` 已有结构质量门和有限 repair，但真实题库质量仍依赖 dataset、人审样本和远程 evaluator 持续校准。当前 deterministic eval 不能替代真实教育质量评估。

### 14.2 旧领域服务仍在兼容层内

`domains.qa.runtime`、`domains.practice.generation`、`domains.mastery.service` 仍被 adapter 复用。审查应重点确认旧实现不会绕过新 contract 泄漏 provider 细节、直接写新边界外表，或把旧 fallback 重新变成生产主路径。

### 14.3 双写和后台任务需要看部署配置

Practice 的 graph-era 双写受环境变量控制：

- `ENABLE_GRAPH_FACTS`
- `ENABLE_GRAPH_DUAL_WRITE`

审查时需要确认目标环境中的配置，否则可能出现“代码支持 graph-era facts，但运行环境未开启双写”的状态。

### 14.4 学习中心依赖数据完整性

学习中心展示质量依赖：

- taxonomy 是否完整。
- `mastery_snapshots` 是否由 MasteryGraph 正常写入。
- `attempts` 是否包含 canonical concept_id。
- 题库 question count 是否与 concept 对齐。

如果这些数据为空或概念未映射，学习中心会正常展示空状态，但“是否达标”需要结合数据初始化和 backfill 情况判断。

### 14.5 当前工作树已有未提交改动

生成本文档时，工作树中已有 practice、小程序前端等未提交改动。本文只描述当前项目架构和代码现状，不代表这些未提交改动已经通过完整测试。Pro 审查应以运行测试和查看 diff 为准。

## 15. 最终达标判断口径

可以认为当前项目在架构层面达到以下条件时为达标：

1. `/api/chat` 生产入口只通过 `LearningOrchestratorGraph`。
2. `LearningOrchestratorGraph` 不直接生成教学回答、题目或 mastery。
3. `QAGraph` 只负责问答、证据、工具 fallback、grounding 和 learning events。
4. `QuestionGenerationGraph` 只负责题目生成、质量门、去重、题目持久化和生成事件。
5. `MasteryEvaluationGraph` 是唯一更新 `mastery_snapshots` 的业务 Graph。
6. 工具调用只通过 capability 层，不在业务 Graph 节点硬编码 Tavily provider。
7. 长期事实写入 PostgreSQL graph-era facts 或 legacy domain tables，不只存在 LangGraph checkpoint。
8. graph-era schema 由 Alembic 管理。
9. 学习中心能从 taxonomy、mastery、attempts、question counts 生成可审计的学习进度读模型。
10. `make test-graphs`、`make eval-graphs`、后端 unittest、必要时前端 lint/build 在审查环境中通过。

