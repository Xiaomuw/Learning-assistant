# 全量功能回归测试报告（含问答主链路加权）

> 历史报告：本文中的 `scripts/check_do_model_access.py` 是当时用于 DigitalOcean 官方 SDK 的外部健康检查脚本；当前项目已删除该脚本与 SDK 依赖。

## 基本信息
- 日期：2026-05-08
- 分支/环境：本地工作区当前版本（已按用户要求排除 LangSmith 真实链路）
- 目标：确认后端自动化 + 问答主链路 + 关键业务链路 + 前端构建质量，区分代码缺陷与外部依赖阻塞
- 关键假设：
  - 默认禁用 LangSmith：`GRAPH_EVAL_LANGSMITH=false`
  - 非外部依赖阻塞时按接口协议完整判定为通过

## 测试范围
- 后端图测试与评测：`make test-graphs`、`make eval-graphs`
- 后端单测：`python -m unittest discover -s tests`
- 问答专项定向测试：`tests.test_chat_api`、`tests.test_qa_graph_adapter`、`tests.test_learning_orchestrator_graph` 等
- 关键 API 抽查：认证、chat、chat/sync、notebook/knowledge、upload、practice、users、model settings
- 前端：`npm run lint`、`npm run build`
- 外部能力：`scripts/check_do_model_access.py`（不含 LangSmith）

## 执行命令与结果

### 1) 后端自动化
- `cd backend && make test-graphs`
  - 结果：`141 tests, OK`
- `cd backend && make eval-graphs`
  - 结果：`6 tests, 6 passed`
- `cd backend && python -m unittest discover -s tests`
  - 结果：`457 tests, OK (skipped=6)`
- 定向问答/路由套件（含 chat/sync 与问答路由适配）
  - `cd backend && python -m unittest tests.test_chat_api tests.test_workflow_routes tests.test_qa_graph_adapter tests.test_qa_graph_runtime_adapter tests.test_learning_orchestrator_graph tests.test_practice_source_normalization tests.test_router_rules`
  - 结果：`69 tests, OK`

### 2) 问答主链路功能验证
- 登录态准备：`POST /api/auth/login`
  - 成功，返回用户与会话 cookie
- `POST /api/auth/me`
  - 成功返回用户信息
- `POST /api/chat/sync`（重点场景）
  - 概念问答：正常返回 `question_type=concept`、`route=explain`、`explanation` 与记忆摘要
  - 题目生成类：返回 `quiz_items`、`quiz_request`、`generation_status`
  - 复习类：返回有效概念解释
- `POST /api/chat`（SSE）
  - 正常事件序列观察到：`status -> routing -> answer_delta* -> explanation -> memory -> status -> done`
  - 未见异常中断
- 鉴权与异常
  - 未登录访问 `/api/chat/sync`：`401 请先登录`
  - token 与 `user_id` 不一致场景：`403 不能使用其他用户身份发起请求`
- `/api/settings/model` 与 `/api/settings/model/health?chat_model=...`
  - 返回正常配置；`chat_model_ok=true`
  - 诊断链路可读，支持 chat/embedding 区分

### 3) 问答关联业务链路抽查
- `/api/notebooks`：返回用户 notebook 列表
- `/api/notebooks/{id}/knowledge/status`：`retrieval_ready=true` 且返回 `doc_count`、缺失类型提示
- `/api/upload/urls`：当前环境下因外部模型链路返回 `model not found`（外部阻塞）
- `/api/practice/packs`
  - topic 不明确时：`need_clarification=true`
  - 明确 topic 时：返回题包与 `generation_status`
- `/api/practice/attempts`：提交/批改成功，返回题目是否正确与 mastery 结果
- 用户数据链路
  - `/api/users/{user_id}/memory`
  - `/api/users/{user_id}/knowledge/mastery`
  - `/api/users/{user_id}/sessions`
  - `/api/users/{user_id}/profile`（GET/PUT）
  - 均可读写

### 4) 前端静态验证
- `cd frontend && npm run lint`
  - 通过
- `cd frontend && npm run build`
  - 通过（11 pages）

### 5) 环境与服务检查
- `backend/scripts/check_environment.py`
  - 通过（提示类告警：embedding/chat 配置提示、SMTP 警告）
- `backend/scripts/check_do_model_access.py`
  - 失败：`inference.do-ai.run` DNS 解析失败（DNS/网络阻断）

## 通过率与阻断
- 自动化测试通过率：**100%**（所有执行套件通过）
- 问答主链路可用：**可用**（`/api/chat` SSE 与 `/api/chat/sync` 正常，回退不崩溃）
- 外部依赖阻断率：**存在**（模型接入 DNS，URL 上传模型路径）
- 前端构建质量：**通过**

## 风险分级
- P0：后端主流程可启动、chat 相关核心接口可用、自动化通过（未触发阻断）
- P1：外部模型服务 DNS 不可达导致真实在线能力受限（环境/网络）
- P2：`/api/upload/urls` 在当前链路下因模型不可达返回 `model not found`（外部阻塞）

## 根因归因（按要求）
- 外部阻塞（网络/DNS）
  - `inference.do-ai.run` 无法解析
  - 影响：`check_do_model_access.py`，模型依赖真实请求，部分上传/问答降级场景
- 外部密钥/配额
  - 当前未出现明确可复现的密钥/配额错误日志；以 DNS 与本地连通性失败为主
- 代码缺陷
  - 未在本轮验证到 chat 主链路协议/结构错误或业务回归（包括 streaming 事件结构与权限隔离）

## 结论
- 以“问答主链路加权”的验收标准：**通过**。
- 其他核心功能链路无阻塞性回归，符合可上线前健康状态；
- 剩余阻断集中在外部模型网络/DNS 与可达性，建议先恢复外网到 DO 推理域名后复测问答在线链路（尤其真实 URL 上传与端到端外调）。


## 2026-05-08 手工问答体验补充（按用户要求）

### 执行上下文
- 验证环境端口：后端 `127.0.0.1:8002`、前端 `127.0.0.1:3001`（当前 compose 映射）
- 登录账号：`test@example.com / password123`（session cookie 自检通过）
- 验证范围：`/api/chat`（后端）+ 前端 API 代理 `/api/chat`（容器）+ `chat/sync` + `sessions/memory/mastery/profile/quiz/latest` + `practice/attempts`
- 注：本次为“手工复核补充”，未使用 GUI 浏览器操作，但覆盖了前端可观察的关键可观测点（SSE 事件、错误码、闭环 API）

### 手工操作记录
1. 登录态准备
   - `POST /api/auth/login` 成功，返回 `user.id = d29a5709-eea7-432f-bd02-175c8c4fdd4a`
2. 三类问题（`chat/sync`）
   - 概念问答：`帮我解释一下哈希表的查找过程`
     - HTTP 200，`question_type=concept`，`route=explain`，含 `explanation` 与 `memory`
   - 出题问答：`给我出3道关于一元函数导数的题`
     - HTTP 200，`question_type=practice`，`quiz_request` 返回且 `quiz_items=[]`，`generation_status` 表示 `explain`，属于题目澄清/质量门前置失败类可读降级
   - 复习问答：`我最近总忘记链式法则，帮我复习一下`
     - HTTP 200，`question_type=concept`，`route=explain`
3. SSE 实时链路（后端）
   - `POST /api/chat`（20s 截取）事件序列：
     - `status` → `routing` → `:ping`（heartbeat）→（超时中止）
   - `answer_delta` 在部分场景出现（如“再给我一个 CPU 的例子”）
   - `explanation`、`memory`、`status(finalized)`、`done` 也在某次采样中完整出现
4. SSE 实时链路（前端代理）
   - `POST http://127.0.0.1:3001/api/chat` 返回：`event: status`、`event: routing`，20 秒内后超时未全部关闭，说明前端代理链路可转发 SSE；超时部分与模型慢回包相关
5. 鉴权与错误态
   - 未登录访问 `POST /api/chat/sync`（不带 cookie）：HTTP 401
   - 鉴权用户不一致 `POST /api/chat/sync`：HTTP 403
6. 会话/历史与闭环
   - `GET /api/users/{user_id}/sessions` 返回多条会话，包含 session 历史与 `latest_quiz`
   - `GET /api/users/{user_id}/quiz/latest` 返回可提交题目
   - `/api/practice/attempts` 提交示例（`selected_option=A`）成功，返回 `is_correct=true` 与 `mastery_evaluation`
   - `GET /api/users/{user_id}/memory /knowledge/mastery /profile` 正常返回
7. 并发/切换场景采样（近实时）
   - 通过短间隔启动两个 SSE：新问题仍可产生独立会话事件流；首条流在后台被 timeout 截断，属于长链路与超时/中断类现象，非 UI 崩溃。

### 手工验收结论
- `/api/chat` 与 `/api/chat/sync` 主体验证通过（协议与返回体结构完整，含错误码与可观测字段）。
- 问答到 `/practice` 闭环可到达：`quiz/latest -> attempt` 可成功提交并返回掌握度评估。
- 关键阻断项与风控
  1. 大模型端点存在超时/阻塞（多次 `/api/chat/sse` 与部分 `model/health`、部分 `chat/sync`/`practice/packs` 长耗时/超时），本次判为外部可用性问题（推断模型链路）
  2. SSE 处理在超时场景出现 `Connection close/cancel`（应用层可见 `Cancelled`/`RuntimeError aclose already running`），不属于前端 UI 代码崩溃行为，表现为可恢复的流式重试现象
- 风险归类
  - P0：问答主链路协议与鉴权边界正常
  - P1：SSE 在部分长耗时问题上的提前超时与可观测中断，需要前端重试提示/用户文案与后端 timeout 策略复核
  - P2：部分端到端请求建议补做本地高可用（模型连通修复后）后复测

## 2026-05-08 SSE 剩余问题收敛记录

- 已修复：`/api/chat` SSE 在客户端断开或前端 idle timeout 后，会先取消并等待 pending chunk，再安全关闭 async generator，避免 `RuntimeError: aclose already running` 把可恢复中断打印成异常堆栈。
- 已修复：SSE `event:error` 继续保留 `error/error_type/retryable/session_id`，并追加 `reason`（如 `workflow_error`、`timeout`、`model_unavailable`），前端据此展示“处理超时 / 模型暂不可用 / 可重试失败”等清晰提示。
- 已验证：`backend/.venv313/bin/python -m unittest backend.tests.test_chat_api backend.tests.test_ingest_service` 通过，新增覆盖安全关闭 pending chunk 后再 `aclose()` 的场景。
- 补充验证：`make test-graphs` 通过（141 tests OK），`make eval-graphs` 通过（6 passed），`npm run lint` 与 `npm run build` 通过。
- 浏览器复测：普通 HTTP 问答正常完成；`Generate two stack practice questions` 与“给我出两道数据库索引练习题”均能从 Chat 生成 2 道题；Practice 可提交并返回掌握度；Dashboard/Profile 可访问。
- 保留外部前置条件：DO 推理域名 DNS/模型可达性仍属于环境依赖；代码侧目标是清晰诊断与 graceful failure，不伪造 URL 入库或模型调用成功。
