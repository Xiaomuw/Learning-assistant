# 多 Agent 学习助手 API 文档

> 更新日期：2026-04-28

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

## 3. 聊天接口

### 3.1 POST `/api/chat`

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
event: explanation
data: {"explanation":{"topic":"HTTP","thinking":"...","steps":["..."],"mistakes":"...","similar":["..."]},"elapsed":2.14}
```

说明：

- `meta` 与 `smalltalk` 路径不会进入检索节点
- `meta_node` 的返回也复用 `explanation` 事件
- 服务端会发送 `ping=10` 心跳，避免长时间无字节输出导致前端误判断线

### 3.2 POST `/api/chat/sync`

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

## 4. 笔记本 / 学科接口

### 4.1 GET `/api/subjects`
### 4.2 GET `/api/notebooks`

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

### 4.3 POST `/api/subjects`
### 4.4 POST `/api/notebooks`

```json
{
  "name": "计算机网络",
  "icon": "🌐",
  "description": "网络协议、分层模型与排障"
}
```

### 4.5 PUT `/api/subjects/{subject_id}`
### 4.6 PUT `/api/notebooks/{subject_id}`

更新名称、图标、简介。

### 4.7 GET `/api/subjects/{subject_id}`
### 4.8 GET `/api/notebooks/{subject_id}`

获取单个笔记本详情。

### 4.9 DELETE `/api/subjects/{subject_id}`
### 4.10 DELETE `/api/notebooks/{subject_id}`

删除结构化记录并尝试删除对应 PGVector collection。

### 4.11 POST `/api/subjects/{subject_id}/generate`
### 4.12 POST `/api/notebooks/{subject_id}/generate`

为没有上传资料的笔记本自动生成基础知识内容并入库。

### 4.13 GET `/api/subjects/{subject_id}/knowledge/status`
### 4.14 GET `/api/notebooks/{subject_id}/knowledge/status`

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

## 5. 知识入库接口

### 5.1 POST `/api/upload`

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

### 5.2 POST `/api/upload/urls`

```json
{
  "subject_id": "computer-network",
  "urls": [
    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview"
  ]
}
```

## 6. 用户数据接口

### 6.1 GET `/api/users/{user_id}/memory`

获取学习记忆。

### 6.2 GET `/api/users/{user_id}/knowledge/mastery?subject_id=...`

获取精细化知识点掌握度。`subject_id` 可选，不传则返回该用户全部 notebook 的统计。

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

### 6.3 GET `/api/users/{user_id}/sessions`

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

### 6.4 DELETE `/api/users/{user_id}/sessions/{session_id}`

删除一条聊天历史。

### 6.5 GET `/api/users/{user_id}/quiz/latest`

获取最近一组题包。

### 6.5 GET `/api/users/{user_id}/profile`

获取用户昵称与 Agent 风格配置。

### 6.6 PUT `/api/users/{user_id}/profile`

```json
{
  "display_name": "学习者_7492",
  "agent_style_name": "苏格拉底教练",
  "agent_style_prompt": "你要像启发式教练一样说话，先提问，再引导，再总结。",
  "onboarding_completed": true
}
```

## 7. 模型配置接口

### 7.1 GET `/api/settings/model`

返回：

- `current_model`
- `embedding_model`
- `available_models`

如果数据库里保存的当前模型不再出现在可选列表内，后端会自动回退到默认或首个可用模型，并写回 `app_settings.chat_model`。

### 7.2 PUT `/api/settings/model`

```json
{
  "chat_model": "openai-gpt-oss-20b"
}
```

约束：

- 只允许非 Claude 聊天模型
- 更新前会做一次轻量可用性校验
- 如果账号当前不能调用该模型，会返回 `400`

## 8. 错误格式

```json
{
  "detail": "错误说明"
}
```
