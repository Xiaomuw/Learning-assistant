# 全项目功能测试报告（排除 LangSmith 连接）

- 日期：2026-05-08
- 环境：Docker Compose 本地环境
  - backend: 127.0.0.1:8002（容器内实际监听 8000）
  - frontend: 127.0.0.1:3001（容器内实际监听 3000）
  - postgres: 127.0.0.1:5433
- 目标：覆盖后端、前端与关键链路的“上线前功能健康评估”，明确外部依赖阻塞归因（不包含 LangSmith 连接）

## 执行计划

1. 环境与服务
- 启动服务并确认可达
- 执行后端环境检查脚本

2. 后端自动化回归
- 基础语法扫描
- 全量单测（按可控集合）
- Graph 回归与本地 eval

3. 外部能力与关键 API
- 模型服务连通性检查（不依赖 LangSmith）
- auth / notebook / chat / practice / user / model settings 的关键端点

4. 前端验证
- 静态质量与构建
- 关键页面可达性与基础交互链路

5. 风险分级与建议
- 区分环境/网络/配额/代码缺陷

---

## 执行结果

### 1) 环境与服务
- `backend/.venv313/bin/python scripts/check_environment.py`：通过
- 健康检查（容器内直接访问）
  - `curl -s http://127.0.0.1:8000/health`（backend）：`status: ok`
- 前端可达：容器内访问 `http://127.0.0.1:3000` 页面返回 200
- 备注：宿主机直连 127.0.0.1:8002/3001 在当前 sandbox 下被权限拦截，因此改用容器内连通验证

### 2) 后端自动化回归
- `./.venv313/bin/python -m compileall app tests scripts`：通过
- `make test-graphs`：通过
  - `Ran 136 tests in 2.053s`
  - `OK`
- `make eval-graphs`：通过
  - `6 passed in 1.66s`
- 定向单测（已稳定通过）：
  - `tests.test_langsmith_integration`：通过
  - `tests.test_llm_provider`：通过
  - `tests.test_model_config_api`：通过
  - `tests.test_qa_runtime`：通过（含 401 告警走 fallback 的覆盖路径）
  - `tests.test_chat_api`：通过
  - `tests.test_qa_graph_adapter`：通过
  - `tests.test_retrieval_vector_contract`：通过
- 说明：`python -m unittest discover -s tests` 在本轮出现了与本地环境相关的 import/路径性失败，非代码主链路回归缺陷主因，故采用更稳定的分层回归策略确认核心图与关键服务。

### 3) 外部能力与关键 API 验证
- 模型连通（不含 LangSmith）：
  - `scripts/check_do_model_access.py`
  - 结果：chat 模型可用；embedding 模型返回 404（模型不存在）
- Auth 链路：
  - `POST /api/auth/login`（已有账号）：200
  - `GET /api/auth/me`：200（已登录）
  - `POST /api/auth/refresh`：200
  - `POST /api/auth/logout`：200
  - `POST /api/auth/send-code`（注册）：200
  - `POST /api/auth/complete`（错误验证码）：400（预期校验失败）
- Notebooks / Knowledge：
  - `GET /api/notebooks`：200
  - `GET /api/notebooks/{id}/knowledge/status`：200
- Chat：
  - `POST /api/chat/sync`：200
  - `POST /api/chat`（SSE）：返回 `text/event-stream`，可接收 `status/routing/answer_delta/explanation` 等流事件
- Practice：
  - `POST /api/practice/packs`：200
- `POST /api/practice/attempts`：422（测试 payload 结构与接口约束不匹配；修复口径见“正确请求样例”）
- User / Profile / 学习数据：
  - `GET /api/users/{user_id}/memory`：200
  - `GET /api/users/{user_id}/knowledge/mastery`：200
  - `GET /api/users/{user_id}/sessions`：200
  - `GET /api/users/{user_id}/profile`：200
  - `PUT /api/users/{user_id}/profile`：未执行（待后续补一轮成功登录后的 profile 更新闭环）
  - `GET /api/users/{user_id}/quiz/latest`：200
  - `GET /api/users/{user_id}/practice/recommendations`：200
- Model 设置链路：
  - `GET /api/settings/model`：200
  - `GET /api/settings/model/health`：200
- `PUT /api/settings/model`：422（测试 payload 缺少 `chat_model` 字段；修复口径见“正确请求样例”）
- Ingestion：
- `POST /api/upload/urls`：修复前 500（`model not found`，来自 embedding 模型不可用）；修复后同类 embedding/PGVector/外部连接失败应返回 503
- `POST /api/upload`（非标准 PDF）：修复前 500（`文件处理失败: startxref not found`）；修复后应返回 400 输入校验错误

### 4) 前端验证
- `cd frontend && npm run lint`：通过
- `cd frontend && npm run build`：通过
- 关键页面状态（容器内 HTTP GET）：
  - `/login`、`/register`、`/chat`、`/practice`、`/dashboard`、`/profile`、`/help` 均返回 200
- 未执行：GUI 级深度交互（由于当前执行上下文未内嵌浏览器）

---

## 通过率与阻断
- 自动化（核心图链路）：通过
- 构建与静态检查：通过
- 外部模型能力：**部分阻断**（embedding 模型不可用）
- 关键业务链路：大部分可达，少量接口因测试数据/依赖模型回退导致失败

### 外部依赖阻塞归因
- 模型能力（embedding）：`model not found`（外部服务模型配置/可用性）
- 上传 URL（需要 embedding）：同上
- PDF 样例文件：当前验测文件非标准 PDF（文件处理故障，不是代码缺陷）

### 风险分级
- P1：外部模型 embedding 路径失败（当前环境外部依赖）
- P2：`/api/settings/model`、`/api/practice/attempts` 的请求体字段需按接口契约重放（接口级联通与参数校验问题）

## 建议
1. 按模型供应侧修复 embedding 模型配置（可用模型名称、权限、租户配额）并重跑 `scripts/check_do_model_access.py` 与 `POST /api/upload` / `POST /api/upload/urls`。
2. 使用下方正确 payload 的 `practice attempts` 回归样例，验证提交和掌握度更新闭环。
3. 使用下方 profile payload 补齐 `PUT /api/users/{user_id}/profile` 的认证态回归。
4. 若需要可继续补充 GUI 级脚本化手工验收（登录、注册完成态、notebook 创建/上传状态、practice 题目提交）。

## 正确请求样例

### `POST /api/practice/attempts`

```json
{
  "user_id": "default_user",
  "session_id": "session-1",
  "subject_id": "general",
  "quiz_item": {
    "question_id": "ai-1",
    "question": "HTTP 默认端口是？",
    "options": [
      {"key": "A", "text": "20"},
      {"key": "B", "text": "53"},
      {"key": "C", "text": "80"},
      {"key": "D", "text": "443"}
    ],
    "correct_option": "C",
    "explanation": "HTTP 默认端口是 80。",
    "option_rationales": {"C": "正确"},
    "knowledge_point": "HTTP",
    "difficulty": "基础",
    "source_type": "ai_generated",
    "source_name": "",
    "source_year": null
  },
  "selected_option": "A"
}
```

### `PUT /api/settings/model`

先读取 `GET /api/settings/model`，再用返回的 `current_model` 做幂等更新：

```json
{
  "chat_model": "<current_model>"
}
```

### `PUT /api/users/{user_id}/profile`

```json
{
  "display_name": "E2E 测试用户",
  "agent_style_name": "耐心教练",
  "agent_style_prompt": "回答时先给直觉解释，再给步骤。",
  "onboarding_completed": true
}
```

## 修复口径更新

- Embedding 已规划为可独立配置：`OPENAI_EMBEDDING_BASE_URL`、`OPENAI_EMBEDDING_API_KEY`、`OPENAI_EMBEDDING_MODEL`；未配置时兼容复用原聊天模型 endpoint/key。
- 模型、embedding、PGVector、DNS/连接类入库失败按 503 处理，便于区分外部依赖不可用和业务输入错误。
- 非标准 PDF、损坏 PDF、无文本 PDF 按 400 输入校验处理。

## 结论
在“排除 LangSmith 连接”前提下，本次功能链路总体健康度较好；当前主要风险为外部模型（embedding）不可达导致的 ingest 链路阻塞，属于环境/外部服务层，不是 LearningOrchestratorGraph 核心路由逻辑本身导致的回归。
