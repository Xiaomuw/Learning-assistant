# 多 Agent 学习助手 API 接口文档

> 版本：v0.1  
> 更新日期：2026-04-12  
> 后端服务默认端口：`8000`

## 1. 接口约定

### 1.1 Base URL

- 后端直连：`http://localhost:8000`
- 前端代理：`/api`

说明：

- 浏览器前端通常通过 `/api` 访问后端。
- Docker 前端容器会把 `/api` 代理到 `backend:8000/api`。

### 1.2 数据格式

- 请求体：`application/json`
- 文件上传：`multipart/form-data`
- 流式响应：`text/event-stream`

### 1.3 认证说明

当前版本未接入登录鉴权，调用方通常使用默认用户 `default_user`。生产环境需补充认证机制。

### 1.4 通用错误格式

```json
{
  "detail": "错误说明"
}
```

## 2. 健康检查

### GET `/health`

用于检查后端服务是否存活。

#### 响应示例

```json
{
  "status": "ok",
  "service": "learning-assistant"
}
```

## 3. 聊天接口

### 3.1 POST `/api/chat`

发起流式聊天请求，返回 SSE 事件流。

#### 请求体

```json
{
  "user_id": "default_user",
  "session_id": "optional-session-id",
  "question": "TCP 和 HTTP 的关系是什么？",
  "subject_id": "general"
}
```

#### 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `user_id` | 是 | 用户 ID |
| `session_id` | 否 | 会话 ID，不传则自动生成 |
| `question` | 是 | 用户问题，1-2000 字符 |
| `subject_id` | 否 | 学科 ID，默认 `general` |

#### SSE 事件类型

| 事件名 | 说明 |
| --- | --- |
| `routing` | 路由结果 |
| `retrieval` | 检索结果摘要 |
| `explanation` | 讲解内容 |
| `quiz` | 练习题 |
| `memory` | 学习记忆更新 |
| `done` | 流结束 |
| `error` | 处理异常 |

#### `routing` 示例

```text
event: routing
data: {"question_type":"concept","elapsed":0.21}
```

#### `retrieval` 示例

```text
event: retrieval
data: {"doc_count":3,"top_scores":[0.91,0.84,0.79],"elapsed":1.42}
```

#### `explanation` 示例

```text
event: explanation
data: {
  "explanation": {
    "topic": "TCP 与 HTTP 的关系",
    "thinking": "……",
    "steps": ["……"],
    "mistakes": ["……"],
    "similar": ["……"]
  },
  "elapsed": 2.36
}
```

### 3.2 POST `/api/chat/sync`

发起同步聊天请求，一次性返回最终结果。

#### 请求体

与 `/api/chat` 相同。

#### 响应示例

```json
{
  "session_id": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1",
  "question_type": "concept",
  "explanation": {
    "topic": "TCP 与 HTTP 的关系",
    "thinking": "HTTP 是应用层协议，TCP 是传输层协议……",
    "steps": [
      "TCP 负责可靠传输",
      "HTTP 负责定义请求与响应语义"
    ],
    "mistakes": [
      "把 HTTP 当成传输协议"
    ],
    "similar": [
      "HTTPS 与 TLS 的关系"
    ]
  },
  "quiz_items": [],
  "memory": {
    "weak_points": [],
    "error_count": {},
    "recent_topics": [
      "TCP 和 HTTP 的关系"
    ],
    "last_session": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1"
  }
}
```

## 4. 学科接口

### 4.1 GET `/api/subjects`

获取全部学科列表。

#### 响应示例

```json
[
  {
    "id": "general",
    "name": "通用知识",
    "icon": "📚",
    "description": "默认通用知识库",
    "doc_count": 12,
    "created_at": "2026-04-12T11:11:11"
  }
]
```

### 4.2 POST `/api/subjects`

创建新学科。

#### 请求体

```json
{
  "name": "计算机网络",
  "icon": "🌐",
  "description": "网络协议、分层模型与排障"
}
```

#### 成功响应

状态码：`201`

```json
{
  "id": "ji-suan-ji-wang-luo",
  "name": "计算机网络",
  "icon": "🌐",
  "description": "网络协议、分层模型与排障",
  "doc_count": 0,
  "created_at": "2026-04-12T11:22:33"
}
```

#### 失败场景

- `409`：学科名称重复

### 4.3 GET `/api/subjects/{subject_id}`

获取单个学科详情。

#### 成功响应

```json
{
  "id": "general",
  "name": "通用知识",
  "icon": "📚",
  "description": "默认通用知识库",
  "doc_count": 12,
  "created_at": "2026-04-12T11:11:11"
}
```

#### 失败场景

- `404`：学科不存在

### 4.4 DELETE `/api/subjects/{subject_id}`

删除学科及其关联知识库。

#### 成功响应

```json
{
  "message": "学科 'general' 已删除"
}
```

### 4.5 POST `/api/subjects/{subject_id}/generate`

为指定学科自动生成知识框架并入库。

#### 成功响应

```json
{
  "subject_id": "computer-network",
  "subject_name": "计算机网络",
  "chapters": 10,
  "total_chunks": 24,
  "chapter_titles": [
    "网络体系结构",
    "传输层协议",
    "应用层协议"
  ],
  "message": "已为 '计算机网络' 生成 10 个章节的知识框架"
}
```

#### 失败场景

- `404`：学科不存在
- `500`：模型生成失败或解析失败

## 5. 知识入库接口

### 5.1 POST `/api/upload`

上传 PDF 文件并写入指定学科的向量库。

#### Content-Type

`multipart/form-data`

#### 表单字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | PDF 文件 |
| `subject_id` | 否 | 学科 ID，默认 `general` |

#### 成功响应

```json
{
  "filename": "network.pdf",
  "total_pages": 18,
  "total_chunks": 37,
  "subject_id": "computer-network",
  "message": "上传并入库成功（学科: computer-network）"
}
```

#### 失败场景

- `400`：非 PDF 文件
- `404`：学科不存在
- `422`：PDF 无法解析或内容为空
- `500`：入库失败

### 5.2 POST `/api/upload/urls`

抓取网页正文并写入指定学科向量库。

#### 请求体

```json
{
  "subject_id": "computer-network",
  "urls": [
    "https://developer.mozilla.org/en-US/docs/Web/HTTP",
    "https://en.wikipedia.org/wiki/Transmission_Control_Protocol"
  ]
}
```

#### 成功响应

```json
{
  "total_urls": 2,
  "successful_urls": 2,
  "total_chunks": 21,
  "subject_id": "computer-network",
  "message": "成功抓取 2/2 个网页"
}
```

#### 失败场景

- `404`：学科不存在
- `422`：所有 URL 内容抓取失败或正文过少

## 6. 用户数据接口

### 6.1 GET `/api/users/{user_id}/memory`

获取用户学习记忆。

#### 响应示例

```json
{
  "weak_points": [
    "HTTP 状态码"
  ],
  "error_count": {
    "HTTP 状态码": 2
  },
  "recent_topics": [
    "TCP 和 HTTP 的关系"
  ],
  "last_session": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1"
}
```

### 6.2 GET `/api/users/{user_id}/sessions`

获取用户全部聊天历史。

#### 响应示例

```json
[
  {
    "id": "497b7d57-b8ab-4b55-91ea-0aa7b60f6ef1",
    "user_id": "default_user",
    "subject_id": "general",
    "title": "TCP 和 HTTP 的关系",
    "messages": [
      {
        "role": "user",
        "content": "TCP 和 HTTP 的关系是什么？",
        "timestamp": 1776000000000
      },
      {
        "role": "assistant",
        "content": "HTTP 是应用层协议……",
        "timestamp": 1776000001000
      }
    ],
    "latest_quiz": [],
    "created_at": "2026-04-12T11:22:33",
    "updated_at": "2026-04-12T11:22:39"
  }
]
```

### 6.3 DELETE `/api/users/{user_id}/sessions/{session_id}`

删除一条聊天历史。

#### 成功响应

```json
{
  "message": "聊天记录已删除"
}
```

#### 失败场景

- `404`：聊天记录不存在

### 6.4 GET `/api/users/{user_id}/quiz/latest`

获取最近一次题包。

#### 响应示例

```json
{
  "quiz_items": [
    {
      "difficulty": "基础",
      "question": "请说明 HTTP 和 HTTPS 的区别。",
      "hint": "从加密与端口角度思考",
      "answer": "HTTPS = HTTP + TLS/SSL……",
      "knowledge_point": "HTTP"
    }
  ]
}
```

## 7. 模型配置接口

### 7.1 GET `/api/settings/model`

获取当前聊天模型与可选模型列表。

#### 响应示例

```json
{
  "current_model": "openai-gpt-oss-20b",
  "embedding_model": "text-embedding-3-small",
  "available_models": [
    {
      "id": "openai-gpt-oss-20b",
      "label": "GPT-OSS-20b",
      "provider": "OpenAI",
      "family": "GPT"
    },
    {
      "id": "llama3.3-70b-instruct",
      "label": "Llama 3.3-70b-instruct",
      "provider": "Meta",
      "family": "Llama"
    }
  ]
}
```

### 7.2 PUT `/api/settings/model`

切换当前聊天模型。

#### 请求体

```json
{
  "chat_model": "openai-gpt-oss-20b"
}
```

#### 成功响应

返回结构与 `GET /api/settings/model` 相同。

#### 失败场景

- `400`：模型不在允许列表内
- `400`：模型当前账号不可用或响应不稳定
- `503`：未能获取可用模型列表

#### 说明

当前系统只允许选择非 Claude 模型。可选模型族以实时拉取结果为准，例如：

- GPT
- Gemini
- Qwen
- Llama
- GLM
- Kimi
- DeepSeek

## 8. 推荐联调顺序

1. 先调用 `GET /health`
2. 再调用 `GET /api/subjects`
3. 确认 `GET /api/settings/model` 返回可用模型
4. 上传资料：`POST /api/upload` 或 `POST /api/upload/urls`
5. 发起问答：`POST /api/chat/sync` 或 `POST /api/chat`
6. 查看学习结果：`GET /api/users/{user_id}/memory`
7. 查看最新题包：`GET /api/users/{user_id}/quiz/latest`

## 9. 当前接口限制

1. 目前没有用户鉴权，接口默认信任调用方传入的 `user_id`。
2. 目前没有会话详情单独查询接口，前端主要通过会话列表恢复历史。
3. 模型切换的可选项依赖外部平台账号权限，接口返回结果是动态的。
