# Architecture Decisions

## ADR-001：新 Graph 骨架放在 `backend/app/orchestration/graphs`

- 背景：项目已有 `backend/app` 分层和结构守卫。
- 决策：不创建顶层 `src/learning_agent`，在现有后端分层内新增 Graph 骨架。
- 原因：避免破坏现有导入路径和维护约定。
- 影响：后续迁移可以逐步进行，生产图不受影响。
- 替代方案：创建新的顶层 `src/` 包；会增加双包维护成本。

## ADR-002：LearningEvent 作为 Graph 间解耦协议

- 背景：当前 QA、出题、掌握度耦合在单一图和共享 state 中。
- 决策：QAGraph 和 QuestionGenerationGraph 通过 `LearningEvent` 向 MasteryEvaluationGraph 传递学习信号。
- 原因：掌握度更新需要可追溯、可重放、可评估。
- 影响：MasteryEvaluationGraph 成为掌握度写入唯一边界。
- 替代方案：各 Graph 直接写 `user_knowledge_stats`；会扩大副作用面。

## ADR-003：工具层按 capability 暴露

- 背景：现有 Tavily 以具体工具名暴露，Graph 容易依赖 provider。
- 决策：Graph 只请求 capability，provider 由 registry 和 policy 决定。
- 原因：便于扩展 web search、web extract、sql read、code execute 等能力。
- 影响：后续 QAGraph 不再直接 import Tavily。
- 替代方案：继续在节点中调用 Tavily；会导致 provider 绑定和权限绕过风险。

## ADR-004：本轮不做数据库迁移

- 状态：已由 ADR-014 取代；此决策只记录架构基线阶段。
- 背景：项目已有 PostgreSQL 表，但缺少 graph/tool/event 事实表。
- 决策：先定义 repository interface 和文档表结构，后续单独迁移。
- 原因：本轮目标是架构基线，不改变生产数据。
- 影响：测试使用 mock repository 验证写入边界。
- 替代方案：直接新增迁移；风险较高且超出本轮范围。

## ADR-005：Orchestrator 路由审计不属于 LearningEvent

- 背景：子代理审计发现当前 Orchestrator stub 使用 `LearningEvent(event_type="orchestrator_routed")` 记录路由行为。
- 决策：Orchestrator 的路由、分支、响应组合、审计记录应进入 `audit_events` 或 `GraphRunRepository.record_audit_event`，不进入业务 `LearningEvent`。
- 原因：`LearningEvent` 是 QA、出题、掌握度之间的学习信号协议；路由行为不是学习事实，也不应被 MasteryEvaluationGraph 消费。
- 影响：后续替换 Orchestrator stub 时，需要把 `orchestrator_routed` 从 `learning_events` 移到 audit event；当前作为已知迁移风险记录。
- 替代方案：保留 `orchestrator_routed` 为非 mastery event；会让事件语义变杂，增加重复消费和报表污染风险。

## ADR-006：跨 Graph 事件类型采用 v0 白名单

- 背景：当前 `LearningEvent.event_type` 仍是自由字符串，后续多 Graph 并行迁移容易出现事件命名漂移。
- 决策：先在 `docs/agent-graphs/cross-graph-contract.md` 定义 v0 事件白名单；代码中新增 `LearningEventType` 常量集合，测试以白名单约束关键事件。
- 原因：在不改公开 schema 的前提下，先建立低成本 contract，避免 QA、出题、掌握度各自发明事件。
- 影响：QAGraph 主要产生 `question_answered`、`concept_explained`、`evidence_used`、`tool_fallback_used`、`insufficient_evidence`、`answer_repaired`；QuestionGenerationGraph 主要产生 `question_generated`、`question_reviewed`、`question_generation_degraded`、`question_generation_failed`。
- 替代方案：立即把 `event_type` 改为枚举；更强但会扩大兼容面，留到子图正式接入时执行。

## ADR-007：Orchestrator 组合响应时保留子图 FinalResponse

- 背景：子代理审计发现当前 Orchestrator `response_composer` 只取 child payload 的 answer，并把 `source_level` 固定为 `none`。
- 决策：正式接入子图时，子图应返回完整 `FinalResponse`；Orchestrator 只追加路由 UI metadata 和审计字段，不压扁 `concepts`、`evidence_refs`、`coach_actions`、`mastery_signals`。
- 原因：证据、教学动作和掌握度信号是子图产物，丢失后会破坏过程面板、审计和后续 mastery 消费。
- 影响：后续替换 stub 时需要调整 adapter output contract，确保 child graph output 可以携带完整 `FinalResponse`。
- 替代方案：继续让 Orchestrator 重组所有字段；会让 Orchestrator 重新承担业务语义，违背边界。

## ADR-008：工具授权应以 capability 白名单和注册风险为准

- 背景：子代理审计指出当前工具策略已 capability 化，但 `notebook_plus_external/open_tools` 的允许面仍偏宽，且执行请求可以低报风险等级。
- 决策：后续工具层收紧为 `SourcePolicy x ToolCapability` 白名单，并把 `ToolRegistration.risk_level` 作为执行请求风险等级的下限。
- 原因：Graph 只能请求 capability，不能通过低报 risk 或直接 provider import 绕过权限。
- 影响：QAGraph、QuestionGenerationGraph、MasteryEvaluationGraph 接入工具时必须声明 `source_policy`、capability、risk level，并由 `ToolPolicyResolver` 统一裁决。当前 `ToolExecutor` 已使用注册风险等级作为执行请求风险等级下限；`SourcePolicy x ToolCapability` 的更细白名单仍可继续收紧。
- 替代方案：依赖每个业务节点自律判断工具权限；会在多 worker 并行迁移时产生越权风险。

## ADR-009：三个业务 Graph 采用 contract-first 后进入生产入口

- 背景：QA、出题、掌握度需要从单体运行链路拆成可观测、可评估、可独立演进的 Graph。
- 决策：先用 contract-first adapter 固定 `FinalResponse`、`LearningEvent`、repository 边界、tool capability 和可序列化 state，再把 `/api/chat` 生产入口切到 `LearningOrchestratorGraph`。
- 原因：先稳定跨图 contract，再切入口，可以降低“接口 shape 变化”和“业务逻辑迁移”混在一起的风险。
- 影响：当前生产入口已由 Orchestrator 承接；子图仍可继续复用 `domains.qa.runtime`、practice generation、mastery domain service。
- 替代方案：在旧单体图内继续堆叠功能；会让副作用、工具权限、掌握度更新和 eval 归因继续耦合。

## ADR-010：Production adapters 只暴露新 Graph contract

- 背景：旧领域服务仍有可复用价值，但旧 graph state 和 shadow/fallback selector 已不再作为生产边界。
- 决策：QAGraph 使用 `ProductionQARuntimeAdapter` 包装 `domains.qa.runtime`；其他业务能力也只能通过 adapter 映射为 shared graph contract，不向 Orchestrator 或 API 泄漏旧结构。
- 原因：保留领域能力，删除旧生产映射，同时避免在新 Graph 外部继续传播历史 state 语义。
- 影响：`/api/chat` 只依赖 `LearningOrchestratorGraph` 和 `FinalResponse` 映射层；测试可继续使用 deterministic / in-memory adapter。
- 替代方案：直接删除所有旧领域服务；短期代码更干净，但会丢失已验证的 QA、practice、mastery 业务能力。

## ADR-011：业务子图不直接互相调用

- 背景：第三阶段需要校准 `QAGraph`、`QuestionGenerationGraph`、`MasteryEvaluationGraph` 的关系，避免后续接真实 runtime 时重新形成单体图耦合。
- 决策：三个业务 Graph 之间禁止直接 import 或调用；只有 `LearningOrchestratorGraph` 可以根据 intent 路由到子 Graph。业务 Graph 间协作必须通过 `LearningEvent`、shared contract 和 repository 摘要间接完成。
- 原因：问答、出题、掌握度分别有不同副作用边界；直接互调会让错误传播、重试循环、repository 写入边界和 eval 归因变得不可控。
- 影响：`QAGraph` 只能输出回答、证据、工具结果和学习事件；`QuestionGenerationGraph` 只能读取 concept/evidence 摘要并写题目；`MasteryEvaluationGraph` 只消费事件/attempt 并写 mastery snapshot。新增 `graph-relationship-matrix.md` 和静态测试约束该关系。
- 替代方案：允许 QAGraph 在回答后直接触发出题或掌握度更新；短期联动更直接，但会破坏 LearningEvent 解耦，也更难做回归归因。

## ADR-012：Graph-era facts 表先沿用 `Base.metadata.create_all()`

- 状态：已由 ADR-014 取代；此决策只记录第六阶段的过渡状态。
- 背景：项目当前没有 Alembic 迁移体系，数据库初始化依赖 `Base.metadata.create_all()` 和少量兼容迁移函数。
- 决策：第六阶段新增 `graph_runs / node_runs / tool_runs / learning_events / attempts / mastery_snapshots` SQLAlchemy models，并沿用现有 create_all 初始化方式；不迁移旧数据，不引入 Alembic。
- 原因：本阶段目标是把 Protocol 落到真实 repository，并为 shadow/eval 提供只写观测能力；引入正式迁移体系会扩大范围和风险。
- 影响：新部署或本地初始化可创建 facts 表；已有数据库需要运行现有初始化流程才能补表。旧 `practice_attempts / user_knowledge_stats` 继续通过 legacy/composite repository 兼容读取。
- 替代方案：立即引入 Alembic 并迁移旧数据；更完整，但会影响生产数据库治理和回滚策略，需要单独阶段评审。

## ADR-013：`make eval-graphs` 先做本地 deterministic smoke eval

- 背景：此前 `make eval-graphs` 是占位，LangSmith dataset/evaluator 还未建立；真实 eval 不应依赖本地 key、Tavily 或生产数据库。
- 决策：第六阶段把 `make eval-graphs` 改为运行本地 deterministic graph eval runner，覆盖 QA / QGen / Mastery contract smoke cases；只有设置 `GRAPH_EVAL_LANGSMITH=true` 且 LangSmith 配置有效时才发送脱敏 trace。
- 原因：先让 eval 命令具备可执行和非零失败语义，避免“占位通过”；同时保持默认无外部依赖，适合本地和 CI。
- 影响：可以声称 `make eval-graphs` 已运行本地 deterministic eval，但不能声称真实 LangSmith dataset/evaluator 已通过。
- 替代方案：等待完整 LangSmith dataset 后再启用 eval；会继续留下占位命令，无法保护当前 contract smoke 风险。

## ADR-014：Graph-era facts schema 进入 Alembic 管理

- 背景：`graph_runs / learning_events / tool_runs / attempts / mastery_snapshots` 已从文档 contract 进入真实 repository，且新增 `question_items / concepts` 后需要正式 schema 变更治理。
- 决策：新增 Alembic 基线 migration `0001_graph_facts` 管理 graph-era facts 表；`Base.metadata.create_all()` 只保留为本地 bootstrap 兼容。
- 原因：facts 表开始承担生产观测和未来灰度事实写入，继续只靠 `create_all()` 无法支撑可审计升级、回滚和环境一致性。
- 影响：部署真实迁移前需要安装 `alembic` 并执行 migration；已有通过 `create_all()` 创建过 facts 表的环境可先 `stamp` 到基线，避免重复建表。
- 替代方案：继续 create_all；短期简单，但无法满足生产 schema 变更治理。

## ADR-015：`/api/chat` 直接切到 LearningOrchestratorGraph

- 背景：用户决定废弃旧 graph/workflow/shadow/fallback 生产映射，直接使用新企业级 Graph 作为测试和后续开发基础。
- 决策：`/api/chat`、`/api/chat/sync` 和 LangGraph Platform 兼容导出均指向 `LearningOrchestratorGraph`；旧 runtime selector、shadow scheduler、canary 和旧 workflow fallback 删除。
- 原因：减少双轨逻辑和历史映射负担，让后续工作集中在新 contract、facts 和 eval 上。
- 影响：公开 API shape 保持兼容，但内部失败不再回退旧 workflow，而是返回新 Graph 结构化错误。
- 替代方案：保留 shadow/canary 双轨；更稳妥，但会持续增加维护成本并干扰架构收口。

## ADR-016：Practice attempt 采用可选 dual-write 接入 Graph-era facts

- 背景：MasteryGraph 要消费 graph-era `attempts / learning_events`，但旧 practice API 已稳定写 `practice_attempts / user_knowledge_stats`。
- 决策：保留旧写入不变；新增 `ENABLE_GRAPH_DUAL_WRITE`，开启后额外写 `attempts` 与 `LearningEvent`，并触发 MasteryGraph 写新 `mastery_snapshots`。
- 原因：可以让 MasteryGraph 进入真实信号链路，又不破坏旧 dashboard 和练习反馈。
- 影响：过渡期会有旧 facts 与新 facts 并存；读取侧通过 composite repository 去重和兼容。
- 替代方案：直接改写 practice API 到新 facts；会影响当前用户反馈和旧掌握度页面。

## ADR-017：Notebook 检索作为 capability provider 接入工具层

- 背景：QAGraph 需要把知识库检索降级为可选工具能力，避免业务节点依赖历史具体工具名或原始 RAG 输出。
- 决策：新增 `notebook_retrieve` provider adapter，复用现有 RAG 检索与 context audit，并把通过审查的内容统一映射为 `ToolResult.evidence`。
- 原因：Notebook 应是模型可用的辅助证据，而不是 Graph 主链路的硬编码前置条件；统一 `ToolResult` 后，后续 web/search/extract 也能走同一审计路径。
- 影响：QAGraph 可以通过 `ToolExecutor / ToolPolicyResolver` 规划 notebook 工具；稳定概念默认不调用工具，`notebook_only` 只允许 notebook，时效/来源类问题才规划 web capability。
- 替代方案：继续在 QA 节点中直接调用 RAG 服务；短期简单，但会绕过工具授权、审计和跨 provider 一致性。

## ADR-018：历史学习事实采用幂等 backfill 复制到 Graph-era facts

- 背景：新 Graph-era facts 已成为长期运行与掌握度事实基础，但旧 `practice_attempts / user_knowledge_stats / question_bank_items` 中仍有历史数据。
- 决策：新增默认 dry-run 的 backfill CLI，使用确定性 ID 把旧事实复制到 `attempts / mastery_snapshots / question_items / concepts`，执行模式必须显式传入 `--execute`。
- 原因：复制式 backfill 能避免破坏旧业务表，同时让 MasteryGraph、QGenGraph 和报表逐步统一到 graph-era facts。
- 影响：Backfill 可重复执行并跳过已存在目标行；真实环境执行前应先看 dry-run 计数，必要时过滤旧实验数据。
- 替代方案：直接迁移并删除旧表；会破坏当前兼容读取和回滚能力，不适合本阶段。

## ADR-019：LangSmith 远程 evaluator 采用显式开关

- 背景：Graph eval 已具备本地 deterministic smoke runner，但真实 LangSmith dataset/evaluator 需要网络、API key 和目标项目配置。
- 决策：本地 `make eval-graphs` 继续离线运行；只有 `GRAPH_EVAL_LANGSMITH=true` 时，`langsmith_eval --sync/--run/--all` 和 `make eval-graphs-remote` 才同步 dataset 并运行远程 evaluator。
- 原因：默认 CI / 本地开发不能依赖外部网络或个人 LangSmith key；远程 eval 仍要有正式闭环，方便上线前校准。
- 影响：远程 payload 只允许 case name、graph type、状态、计数、错误类型和耗时等摘要，不允许上传用户原文、答案全文、notebook 原文、完整 prompt 或 tool args。
- 替代方案：默认让 `make eval-graphs` 访问 LangSmith；会导致无 key 环境失败，并增加敏感内容上传风险。

## ADR-020：QA Runtime 工具名以 capability 为主

- 背景：旧 QA runtime tool loop 使用 provider 具体工具名判断 notebook、Tavily、MCP 等路径，容易把 provider 名泄漏到 Graph contract、LangSmith metadata 和过程摘要。
- 决策：模型可见工具名统一改为 `notebook_retrieve / web_search / web_extract / session_summary / learning_profile / question_recommend`；旧 notebook、Tavily、MCP 等实现只保留在 adapter/provider 层。
- 原因：业务 Graph 和 runtime 决策应按能力而不是 provider 分支，才能让 Tavily 只是 `web_search` 的一个 provider，并为后续工具扩展留出统一权限边界。
- 影响：`domains.qa.tool_loop` 按 capability/provider 摘要记录 source usage、tool decision 和 trace metadata；新生成的 process summary 不再出现历史 provider 工具名。旧历史消息仍由展示层兼容映射为通用 capability 标签。
- 替代方案：继续让 runtime 暴露 provider 工具名；短期少改代码，但会破坏 capability-based 工具治理和跨 provider 可观测性。

## ADR-021：Orchestrator 子图调用边界采用 ChildGraphInvoker

- 背景：`LearningOrchestratorGraph` 已成为 `/api/chat` 生产入口，子图调用需要避免把 QA、出题、掌握度的 runtime 细节继续堆在 Orchestrator node 中。
- 决策：Orchestrator 到业务子图的唯一调用边界是 `ChildGraphInvokerFactory / ChildGraphInvoker`。Orchestrator node 只委托 invoker；child state 组装、child graph invoke、`ChildGraphOutput` 映射集中在 invoker 层。
- 原因：这让路由、子图运行和响应组合分离，避免 `nodes.py` 重新变成高分支编排点，也便于后续把 production dependency wiring 抽到专门 composition builder。
- 事实写入责任：业务领域事实原则上由子 Graph production build 通过对应 repository 写入。现有 `/api/chat` runtime 的 child facts 汇总写入视为兼容期 facts 转发器，不属于 Orchestrator Graph 节点职责；后续收口时应避免与子图内部写入重复。
- 影响：业务 Graph 仍只能通过 shared contract、repository Protocol 和 `LearningEvent` 协作；Orchestrator 仍只负责路由、上下文加载、响应组合和运行审计。
- 替代方案：继续在 Orchestrator node 内直接构造每个子图的生产依赖；短期少文件，但会让 Orchestrator 知道过多子领域 runtime 细节。
