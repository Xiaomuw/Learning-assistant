# Graph Integration Checklist

## QAGraph 接入检查项

- 已完成：建立 `ProductionQARuntimeAdapter`，只复用 `domains.qa.runtime`，并把输出收敛为 shared graph contract。
- 把 `QAGraphState` 映射为 `AgentRequest`，再把 `AnswerSchema`、证据、工具结果映射为 `FinalResponse`。
- 已完成：只把通过审查的 context 转成 `EvidenceChunk`，禁止 raw retrieved docs 进入最终证据。
- 已完成：产生 `question_answered`、`concept_explained`、`evidence_used`、`insufficient_evidence`。
- 已完成：只写 `LearningEventRepository`，不写 mastery、question item、attempt、chat session。
- 已完成：`notebook_only` 下阻止 `web_search`。
- 已完成：可注入 `ToolExecutor` 执行 capability request；默认不执行外部工具。
- 已完成：新增正式 `notebook_retrieve` provider adapter，把旧 RAG 输出标准化为 `ToolResult.evidence`。
- 已完成：稳定概念默认不规划工具；`notebook_only` 只允许 notebook；时效/来源类问题才规划 web capability。
- 已完成：真实 runtime 内部 tool loop 已改为 capability 工具名，历史 provider 工具名只保留在 adapter 内部。
- 已完成：工具循环上限保持 3 轮，不引入无限 repair / retry loop。

## QuestionGenerationGraph 接入检查项

- 已完成：补齐 `QuestionItem`、`SourceRef`、`AnswerKey`、`Rubric`、`QualityReport` schema。
- 已完成：以现有 `PracticeRecommendation` 字段为兼容底座，新增 `LegacyPracticeQuestionCandidateGenerator`。
- 已完成：拆出 blueprint、candidate generation、solver verifier、quality reviewer、dedupe、persist、compose response。
- 已完成：`source_refs` 可追踪到 `EvidenceChunk` 或 generator/provenance 来源。
- 已完成：`answer_key` 包含正确选项、正确选项文本、标准解析、option rationales。
- 已完成：quality gate 检查结构、唯一答案、难度、知识点相关性、重复题、source policy grounding。
- 已完成：只写 `QuestionItemRepository` 和生成类 `LearningEvent`，不写 mastery。
- 已完成：失败后有限 retry 已接入 candidate generation 路径并有测试覆盖。
- 已完成：新 graph contract 不再暴露 `legacy_*` 语义；旧 practice generator 仅作为内部兼容实现。
- 待完成：用真实题库 dataset / 人审样本持续校准题目质量。

## MasteryEvaluationGraph 接入检查项

- 已完成：支持消费 `LearningEvent` 和 attempt payload。
- 已完成：strong signal：已评分练习、MCQ、标准答案题、solver verified。
- 已完成：medium signal：rubric/LLM 评分短答、部分正确答案。
- 已完成：weak signal：讲解曝光、证据使用、提示请求、卡住、工具 fallback。
- 已完成：p_mastery bounded update，单次强信号不能无界跳变。
- 已完成：弱曝光不能覆盖 strong evidence。
- 已完成：同一个 `LearningEvent.id` 或 `attempt_id` 只能消费一次。
- 已完成：只有 MasteryEvaluationGraph 写 `MasterySnapshotRepository`。
- 已完成：新增历史 knowledge stats 兼容 repository adapter，默认只读。
- 已完成：新增幂等 backfill CLI，把旧 `practice_attempts / user_knowledge_stats / question_bank_items` 映射到 graph-era facts。
- 已完成：生产提交路径已通过 finalizer / repository adapter 把兼容 `practice_attempts` 转成 graph-era attempt，再交给 mastery 路径消费。
- 已完成：旧 repository 已补齐安全的 recent attempts read adapter，供组合仓储兼容读取。

## 三者合并前检查项

- 所有子 Graph 输出都可被 `FinalResponse.model_validate` 验证。
- `FinalResponse.evidence_refs` 都能在 `state.evidence` 或 `tool_results[*].evidence` 中找到。
- `LearningEvent.event_type` 必须属于跨图契约清单。
- Orchestrator 路由审计只进入 `audit_events`，不进入业务 `LearningEvent`。
- 所有 Graph State 可 JSON 序列化。
- 业务 Graph 不能 import provider-specific Tavily 模块。
- repository 写入必须通过 Protocol / adapter。
- `/api/chat` 已接入 `LearningOrchestratorGraph`，但公开 request/response/SSE shape 必须保持兼容。

## 合并顺序

1. QAGraph：先包住现有 QA runtime，产出 `FinalResponse + LearningEvent`。
2. QuestionGenerationGraph：迁移 quiz flow，产出 `QuestionItem + quality_report + LearningEvent`。
3. MasteryEvaluationGraph：接 attempt/event 消费和 bounded mastery update。
4. Orchestrator：已调用三个业务子图 adapter。
5. 生产入口：`/api/chat` 已通过 Orchestrator，后续只允许在兼容 response shape 内迭代。

## 回归测试命令

最小新增测试：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_cross_graph_contracts
```

Graph 基线测试：

```bash
make test-graphs
```

当前 `make test-graphs` 已包含 cross graph contract、QA / QuestionGeneration / Mastery adapter、graph persistence、migration、backfill 与 eval runner 测试。

新生产入口保护：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_workflow_routes backend.tests.test_langgraph_platform backend.tests.test_architecture_boundaries
```

QAGraph 迁移时建议：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_qa_runtime backend.tests.test_rag_module backend.tests.test_workflow_routes
```

QuestionGenerationGraph 迁移时建议：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_quiz_flow_nodes backend.tests.test_quiz_agent backend.tests.test_practice_api
```

MasteryEvaluationGraph 迁移时建议：

```bash
backend/.venv313/bin/python -m unittest backend.tests.test_mastery_evaluation backend.tests.test_practice_api
```

如果修改前端或共享接口：

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

`make eval-graphs` 已运行 6 个本地 deterministic eval；远程 LangSmith evaluator 需要显式执行：

```bash
GRAPH_EVAL_LANGSMITH=true make eval-graphs-remote
```

未配置网络 / key 时，不要声称远程 LangSmith eval 已通过。

## 风险清单

- Orchestrator 可能把路由审计误写成业务 `LearningEvent`。
- 旧 provider/tool 实现仍存在于兼容层；新 Graph 边界与 QA runtime tool loop 已只暴露 capability。
- `LearningEvent.event_type` 目前是自由字符串，后续需要枚举或测试白名单。
- `ToolPolicyResolver` 已覆盖 `notebook_only / notebook_plus_external / open_tools` 基础矩阵；后续新增高风险 capability 时还需要单独审批策略。
- QuestionGenerationGraph 的 `question_generated` 是生成审计还是 mastery 信号，需要保持“非 mastery 信号”。
- MasteryEvaluationGraph 迁移需要幂等，否则可能重复消费 attempt/event。
