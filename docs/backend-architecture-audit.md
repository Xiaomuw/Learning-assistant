# 后端架构审计报告

> 审计日期：2026-04-15  
> 范围：`backend/`、核心文档、最小测试门禁

> **历史参考说明**：这份审计报告记录整改前状态，里面的 Chroma / MySQL 等描述不是当前运行事实。当前事实请看 [项目当前状态](project-current-status.md)、[后端目录能力地图](backend-map.md) 和实际 `backend/app/*`。

## 1. 结论摘要

当前后端 **已经具备清晰的基础轮廓**，并且真实建立在：

- FastAPI
- LangGraph `StateGraph`
- LangChain 模型调用
- Chroma RAG
- MySQL 持久化

之上，所以它不是“技术栈挂名”。  
但在本次整改前，仍存在一批会误导接手者判断的问题：注释与实现不一致、结构化输出名不副实、文档与运行端口漂移、产品 notebook 语义与内部 subject 命名未被明确解释。

## 2. 四维评分

| 维度 | 分数 | 说明 |
| --- | --- | --- |
| 结构清晰度 | 8/10 | 基础分层成立，但曾有注释/职责漂移 |
| LangChain / LangGraph 契合度 | 8/10 | 工作流真实存在，结构化输出整改后明显改善 |
| 产品需求匹配度 | 7/10 | 主流程可用，但 notebook / subject 语义曾混淆 |
| 运行与维护风险 | 7/10 | 主要风险来自文档漂移、测试不足、历史兼容命名 |

## 3. P0 / P1 / P2 问题分级

### P0

1. 注释声称使用 structured output，但节点实际手工解析 JSON  
   影响：容易在模型输出波动时脆断，也会误导后续开发者对 LangChain 用法的判断。

2. `MemorySaver` 被写成“会话持久化”  
   影响：会让人误判图状态已经具备真正跨请求持久化能力，而当前长期事实其实在 MySQL。

3. 文档与真实运行行为漂移  
   影响：端口、模型来源、路径分流、Docker 行为与现实不一致，接手成本高。

### P1

1. notebook 产品语义与 `subject` 内部命名未被清楚解释  
2. 检索层曾存在重复 / 误导性的抽象
3. `AgentState` 契约缺少节点读写说明

### P2

1. 仍未做数据库层物理 `subject -> notebook` 迁移
2. 自动化测试仍然是“最小集”，不是完整回归网
3. 上传与知识生成链路仍有进一步领域化空间

## 4. 本次已完成整改

### 4.1 架构与代码

- Router 改为真正的 structured output
- Retriever 改为真正的 structured output
- Explainer 改为真正的 structured output
- Quiz 改为真正的 structured output
- 移除 LangGraph `MemorySaver` 依赖
- 当时曾明确以 MySQL 作为长期事实来源；当前已演进为 PostgreSQL
- 清理 Agent 内部重复的检索抽象
- 补充 `AgentState` 节点读写契约说明
- 提供 `/api/notebooks` 兼容别名层

### 4.2 文档

- 更新 `README.md`
- 更新技术文档
- 更新 API 文档
- 新增本审计报告

### 4.3 测试

新增最小后端测试集，覆盖：

- Router 分类
- 工作流分流
- `/api/chat/sync`
- SSE 事件序列
- 模型配置回退与校验失败
- Repository 初始化与核心 CRUD
- 空知识库检索兜底

## 5. 当前架构判断

### 5.1 是否符合 LangChain / LangGraph 技术栈

符合，且现在比整改前更正统：

- 用 `StateGraph` 做节点编排
- 用结构化 schema 做输出契约
- 用统一 provider 初始化模型
- 用外部数据库承担长期状态，而不是把进程内对象误当持久化层

### 5.2 是否符合当前产品需求

基本符合当前需求：

- H5 学习助手
- notebook / 资料库
- 用户级 Agent 风格
- 隔离知识库
- 历史会话
- 学习记忆
- 模型切换

仍保留的现实折中：

- 内部字段和数据库表暂时还是 `subject`
- 这是兼容策略，不是最终产品语义

## 6. 建议的下一阶段

1. 评估是否要做 `subject -> notebook` 的数据库与接口二阶段迁移
2. 把现有最小测试集扩成 CI 门禁
3. 为上传 / 抓取 / 自动生成链路补更多领域级校验
4. 如果后续需要真正的跨请求图恢复，再引入持久化 checkpointer，而不是恢复 `MemorySaver`
