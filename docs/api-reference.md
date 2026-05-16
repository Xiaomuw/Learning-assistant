# 多 Agent 学习助手 API 文档

> 更新日期：2026-05-12

## 1. Base URL

### 本地开发

- 后端：`http://127.0.0.1:8000`
- 前端代理：`/api`

### Docker

- 宿主机访问后端：`http://127.0.0.1:8002`
- 前端容器内部代理到：`http://backend:8000/api`

说明：

- 浏览器优先通过前端代理 `/api` 访问
- `/api/subjects` 与 `/api/notebooks` 当前等价
- 字段 `subject_id` 仍是兼容实现，产品语义上可理解为 `notebook_id`

## 2. 健康检查

### GET `/health`

```json
{
  "status": "ok",
  "service": "learning-assistant"
}
```

## 3. 认证接口

认证接口统一挂在 `/api/auth/*`，浏览器端使用 `HttpOnly Cookie` 保存 access / refresh；微信小程序路径返回 token envelope。

### 3.1 POST `/api/auth/register/send-code`

发送邮箱注册验证码。SMTP 未配置时会返回明确错误，不会假装发信。

### 3.2 POST `/api/auth/register/complete`

使用邮箱、验证码和密码完成注册，并写入登录 cookie。

### 3.3 POST `/api/auth/register`

兼容注册入口。

### 3.4 POST `/api/auth/login`

邮箱密码登录，并写入登录 cookie。

### 3.5 POST `/api/auth/refresh`

刷新 access token。

### 3.6 POST `/api/auth/logout`

注销当前 refresh token 并清理 cookie。

### 3.7 POST `/api/auth/change-password`

修改当前用户密码。

### 3.8 GET `/api/auth/me`

返回当前登录用户 envelope。

### 3.9 微信小程序认证

- `POST /api/auth/wechat-mini/login`
- `POST /api/auth/wechat-mini/refresh`
- `POST /api/auth/wechat-mini/logout`

## 4. 聊天接口

### 4.1 POST `/api/chat`

SSE 流式接口。

#### 请求体

```json
{
  "user_id": "当前登录用户 ID",
  "session_id": "optional-session-id",
  "question": "TCP 和 HTTP 的关系是什么？",
  "subject_id": "computer-network",
  "thinking_mode": false
}
```

`thinking_mode` 可选，默认 `false`。设为 `true` 时，本轮 DeepSeek V4 请求启用 thinking；接口仍只返回安全进度摘要和最终回答，不返回原始 `reasoning_content`。

LangSmith tracing 开启后会记录用户原始问题、路由、工具调用、检索摘要、模型选择、最终答案和安全推理摘要。原始 `reasoning_content` / chain-of-thought 会被脱敏，不会写入 LangSmith。

#### SSE 事件类型

| 事件 | 说明 |
| --- | --- |
| `status` | 已接入引擎，开始处理 |
| `routing` | 问题分类完成 |
| `retrieval` | 检索结果摘要 |
| `answer_delta` | 回答正文片段；前端可边收边追加显示 |
| `reasoning_delta` | 思考模式调试片段；仅本轮临时展示，不写入正常回答 |
| `explanation` | 讲解结果或元问题回答 |
| `quiz` | 题包结果 |
| `memory` | 学习记忆更新 |
| `done` | 正常结束 |
| `error` | 处理异常 |

#### 事件示例

```text
event: status
data: {"message":"已连接学习引擎，正在判断问题类型。","session_id":"..."}
```

```text
event: routing
data: {"question_type":"smalltalk","elapsed":0.02}
```

```text
event: retrieval
data: {"doc_count":3,"top_scores":[0.91,0.84,0.79],"elapsed":1.28}
```

```text
event: answer_delta
data: {"delta":"HTTP 是","streaming_mode":"token","is_synthetic_delta":false}
```

```text
event: explanation
data: {"explanation":{"topic":"HTTP","thinking":"...","steps":["..."],"mistakes":"...","similar":["..."]},"elapsed":2.14}
```

说明：

- `meta` 与 `smalltalk` 路径不会进入检索节点
- `meta / smalltalk` 等非检索回答也复用 `explanation` 事件
- 支持 token 的模型路径会在最终 `explanation` 前发送 `answer_delta`
- 服务端会发送 `ping=10` 心跳，避免长时间无字节输出导致前端误判断线

### 4.2 POST `/api/chat/sync`

同步接口，一次性返回最终状态摘要。
请求体与 `/api/chat` 相同，支持可选 `thinking_mode`。

#### 响应示例

```json
{
  "session_id": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1",
  "question_type": "concept",
  "explanation": {
    "topic": "HTTP",
    "thinking": "HTTP 是应用层协议。",
    "steps": ["定义请求与响应语义"],
    "mistakes": "不要把 HTTP 误认为传输层协议",
    "similar": ["HTTPS"]
  },
  "quiz_items": [],
  "memory": {
    "weak_points": ["HTTP"],
    "error_count": {"HTTP": 1},
    "recent_topics": ["HTTP"],
    "last_session": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1@2026-04-15T00:00:00Z"
  }
}
```

## 5. 笔记本 / 学科接口

### 5.1 GET `/api/subjects`
### 5.2 GET `/api/notebooks`

返回相同结果：

```json
[
  {
    "id": "data-structure",
    "name": "数据结构与算法",
    "icon": "🌳",
    "description": "线性表、树、图、排序、查找、动态规划、贪心等",
    "doc_count": 12,
    "created_at": "2026-04-12T11:11:11Z"
  }
]
```

当前产品只展示四个固定知识库：`data-structure`、`computer-network`、
`computer-organization`、`operating-system`。旧的 `general` 等历史知识库不再作为可选项；
模型通用知识由模型自身提供，知识库只作为辅助参考。

### 5.3 POST `/api/subjects`
### 5.4 POST `/api/notebooks`

```json
{
  "name": "计算机网络",
  "icon": "🌐",
  "description": "网络协议、分层模型与排障"
}
```

### 5.5 PUT `/api/subjects/{subject_id}`
### 5.6 PUT `/api/notebooks/{subject_id}`

更新名称、图标、简介。

### 5.7 GET `/api/subjects/{subject_id}`
### 5.8 GET `/api/notebooks/{subject_id}`

获取单个笔记本详情。

### 5.9 DELETE `/api/subjects/{subject_id}`
### 5.10 DELETE `/api/notebooks/{subject_id}`

删除结构化记录并尝试删除对应 PGVector collection。

### 5.11 POST `/api/subjects/{subject_id}/generate`
### 5.12 POST `/api/notebooks/{subject_id}/generate`

为没有上传资料的笔记本自动生成基础知识内容并入库。

### 5.13 GET `/api/subjects/{subject_id}/knowledge/status`
### 5.14 GET `/api/notebooks/{subject_id}/knowledge/status`

查看 notebook 对应 PGVector 知识库状态：

```json
{
  "subject_id": "computer-network",
  "collection_name": "learning_computer-network",
  "doc_count": 24,
  "chapter_count": 8,
  "question_count": 6,
  "url_count": 4,
  "pdf_count": 6,
  "embedding_ready": true
}
```

## 6. 知识入库接口

### 6.1 POST `/api/upload`

`multipart/form-data`

字段：

- `file`: PDF 文件
- `subject_id`: 目标笔记本 ID

响应示例：

```json
{
  "filename": "tcp.pdf",
  "total_pages": 8,
  "total_chunks": 26,
  "subject_id": "computer-network",
  "message": "上传并入库成功（学科: computer-network）"
}
```

### 6.2 POST `/api/upload/urls`

```json
{
  "subject_id": "computer-network",
  "urls": [
    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview"
  ]
}
```

## 7. 用户数据与练习接口

### 7.1 GET `/api/users/{user_id}/memory`

获取学习记忆。

### 7.2 GET `/api/users/{user_id}/knowledge/mastery?subject_id=...`

获取掌握度视图。`subject_id` 可选，不传则返回该用户全部 notebook 的统计；当前后端可从 graph-era `mastery_snapshots` 和历史兼容数据聚合。

```json
{
  "user_id": "user-1",
  "subject_id": "computer-network",
  "items": [
    {
      "knowledge_point": "HTTP 缓存",
      "exposure_count": 3,
      "attempt_count": 2,
      "correct_count": 1,
      "wrong_count": 1,
      "mastery_score": 45,
      "mastery_level": "weak"
    }
  ]
}
```

### 7.3 GET `/api/users/{user_id}/learning-center`

获取学习中心聚合数据。

### 7.4 GET `/api/users/{user_id}/sessions`

获取最近聊天历史。

每条 session 现在额外包含：

- `session_memory`
  - `summary_text`
  - `active_topic`
  - `current_goal`
  - `open_loops`
  - `resolved_points`
  - `last_question_type`
  - `last_updated_at`

### 7.5 DELETE `/api/users/{user_id}/sessions/{session_id}`

删除一条聊天历史。

### 7.6 GET `/api/users/{user_id}/quiz/latest`

获取最近一组题包。

### 7.7 GET `/api/users/{user_id}/profile`

获取用户昵称与 Agent 风格配置。

### 7.8 PUT `/api/users/{user_id}/profile`

```json
{
  "display_name": "学习者_7492",
  "agent_style_name": "苏格拉底教练",
  "agent_style_prompt": "你要像启发式教练一样说话，先提问，再引导，再总结。",
  "onboarding_completed": true
}
```

### 7.9 GET `/api/users/{user_id}/practice/recommendations`

获取当前用户推荐练习。

### 7.10 POST `/api/practice/attempts`

提交选择题作答。接口保持兼容写入 `practice_attempts`，同时通过 finalizer / repository 路径进入 graph-era facts。

### 7.11 POST `/api/practice/packs`

生成或补齐练习题包，供 Practice 页基于当前题目知识点继续 AI 补题。

## 8. 模型配置与观测接口

### 8.1 GET `/api/settings/model`

返回：

- `current_model`
- `embedding_model`
- `available_models`

如果数据库里保存的当前模型不再出现在可选列表内，后端会自动回退到默认或首个可用模型，并写回 `app_settings.chat_model`。

### 8.2 PUT `/api/settings/model`

```json
{
  "chat_model": "openai-gpt-oss-20b"
}
```

约束：

- 只允许非 Claude 聊天模型
- 更新前会做一次轻量可用性校验
- 如果账号当前不能调用该模型，会返回 `400`

### 8.3 GET `/api/settings/model/health`

检查当前模型配置和轻量可用性状态。

### 8.4 GET `/api/settings/observability/langsmith/health`

检查 LangSmith 观测配置状态。该接口只代表配置与连通性状态，不等于 remote evaluator 已运行。

## 9. 错误格式

```json
{
  "detail": "错误说明"
}
```
