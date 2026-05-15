# Graph Eval Matrix

## QAGraph

核心场景：

- 稳定概念直接讲解，不被 Notebook 缺失阻塞。
- `notebook_only` 时只依据 Notebook，资料不足则明确不足。
- 时效/官网/来源类问题通过 `web_search` capability。
- 低相关证据不进入最终回答。

指标：

- answer correctness
- grounding precision
- unsupported claim rate
- tool precision
- source policy compliance
- final answer UX quality

## QuestionGenerationGraph

核心场景：

- 根据知识点生成候选题。
- solver verifier 能验证答案唯一。
- quality reviewer 能拦截含糊题、重复题和难度不匹配题。
- dedupe 能避免同一题反复出现。

指标：

- answer validity
- distractor quality
- difficulty alignment
- duplication rate
- curriculum coverage

## MasteryEvaluationGraph

核心场景：

- 消费 QA 和练习事件。
- 评分并抽取弱信号。
- 更新掌握度。
- 传播先修知识影响。
- 输出下一步学习建议。

指标：

- scoring consistency
- mastery stability
- prerequisite propagation accuracy
- recommendation usefulness

## 测试目标命令

```bash
make test-graphs
```

QA 路由、QAGraph trace、移动同步交付的重点回归测试：

```bash
backend/.venv313/bin/python -m unittest \
  backend.tests.test_route_decider \
  backend.tests.test_orchestrator_intent_rules \
  backend.tests.test_qa_graph_adapter \
  backend.tests.test_chat_api
```

这些测试覆盖：

- `simple_fact` 不进入 RAG、不调用 web。
- `practice_generation` 绕过 QAGraph。
- `meta_tool_usage` 只读取真实工具 trace。
- `realtime_or_fresh` 在允许联网时才可进入 web 路径。
- `notebook_only` 证据不足时不越权联网、不编造确定答案。
- `answer_repair` 受最大次数限制，不进入无限修复。
- `/api/chat/sync` 的 `completed / pending` 响应，以及 `POST /api/chat/jobs/{job_id}/poll` 的完成、失败、过期、幂等边界。

本地 deterministic eval：

```bash
make eval-graphs
```

当前 `make eval-graphs` 会执行：

- `route_simple_fact`
- `route_exercise_generation`
- `route_meta_tool_usage`
- `route_latest_allow_web`
- `route_latest_without_web`
- `qa_concept_filtered_retrieval`
- `qa_explicit_web_fallback`
- `qa_tool_policy_stable_concept_no_tools`
- `qa_notebook_only_insufficient`
- `qa_tutoring_sufficient_evidence`
- `qgen_evidence_grounded`
- `mastery_attempt_bounded_update`
- `mastery_weak_signal_small_delta`

默认 eval 不依赖真实 LLM、Tavily、生产数据库或 LangSmith。若设置 `GRAPH_EVAL_LANGSMITH=true` 且 LangSmith 已配置，则每个 eval case 会发送脱敏 trace，run name 形如 `graph.eval.<case>`。

## QA Trace Records

为了排查路由、证据、工具、修复和移动端交付问题，Graph State 会维护 `trace_records`。这些记录只包含可脱敏的运行事实，不包含用户全文、prompt、token、密钥、Authorization header 或外部工具原始 payload。

当前约定的关键 stage：

- `route_decider`：记录 route、target graph、是否绕过 QAGraph、是否读取 trace、`allow_web`、`notebook_only`、web capability。
- `internal_retrieval`：记录 RAG 是否计划/实际调用、请求数、结果数、成功/错误计数。
- `web_search_if_needed`：记录 web 是否计划/实际调用、触发原因、请求数、结果数、成功/错误计数。
- `internal_evidence_judge`：记录内部证据置信度 `score / level / threshold / sufficient / reason`。
- `external_evidence_judge`：记录外部证据置信度 `score / level / threshold / sufficient / reason`。
- `answer_quality_check`：记录质量检查状态、是否通过、修复动作和修复次数。
- `answer_repair`：记录当前修复次数、最大修复次数和修复结果。
- `final_response`：记录最终响应状态，例如 `completed`、`clarification_required` 或 insufficient evidence。
- `mobile_sync_delivery`：记录移动同步接口返回 `pending` 时的 `job_id`、`request_id`、`retry_after_ms`。

验收时可从 API 响应的 `trace_records` 或云托管日志确认以下事实一致：

- UI 显示 `0 次工具调用` 时，trace 中不应出现 `web_called=true`。
- `notebook_only` 的 trace 中不应出现 `web_called=true`。
- 证据不足路径应出现 insufficient/clarification 类 final status，而不是伪造高置信度回答。
- 移动端 pending 响应必须带 `retry_after_ms`，poll 由服务端 job 过期时间兜底，不能无限等待。

可选 LangSmith dataset / evaluator：

```bash
cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --sync
cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --run
cd backend && ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --all
GRAPH_EVAL_LANGSMITH=true make eval-graphs-remote
```

默认 `GRAPH_EVAL_LANGSMITH=false` 时只输出本地 dataset preview，不访问 LangSmith。开启后会创建/补充 `GRAPH_EVAL_DATASET` 指定的数据集示例并运行 deterministic evaluator。payload 只包含 case name、graph type、状态、计数、错误类型和摘要指标，不包含用户原文、答案全文、notebook 原文、完整 prompt 或 tool args。

远程 evaluator：

- `qa_groundedness`：验证 notebook-only 不编造、稳定概念可直接回答。
- `tool_policy_precision`：验证稳定概念不调用工具、`notebook_only` 不越权 web。
- `qgen_quality`：验证 source refs、answer key、rubric、quality pass。
- `mastery_stability`：验证 `p_mastery` bounded、weak signal 小幅更新。

后续目标：

- 在真实 LangSmith 项目中积累更多 dataset case。
- 在 CI 中区分 smoke eval 与真实 dataset eval，避免无 key 环境失败。
