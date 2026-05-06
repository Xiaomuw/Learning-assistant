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

本地 deterministic eval：

```bash
make eval-graphs
```

当前 `make eval-graphs` 会执行：

- `qa_model_only_concept`
- `qa_tool_policy_stable_concept_no_tools`
- `qa_notebook_only_insufficient`
- `qgen_evidence_grounded`
- `mastery_attempt_bounded_update`
- `mastery_weak_signal_small_delta`

默认 eval 不依赖真实 LLM、Tavily、生产数据库或 LangSmith。若设置 `GRAPH_EVAL_LANGSMITH=true` 且 LangSmith 已配置，则每个 eval case 会发送脱敏 trace，run name 形如 `graph.eval.<case>`。

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
