# 主要功能流程图

> 目标：让人和 AI 快速理解“请求从哪里进、经过哪些层、最后写到哪里”。  
> 图里使用 notebook 产品语义；如果看到 `subject_id`，它是后端兼容字段。

## 1. 登录与注册

```mermaid
flowchart TD
    A["注册页输入邮箱"] --> B["POST /api/auth/register/send-code"]
    B --> C["application/auth/verification.py"]
    C --> D["SMTP 发 6 位验证码"]
    A2["输入验证码 + 密码"] --> E["POST /api/auth/register/complete"]
    E --> F["创建 users / user_profiles / user_memories"]
    F --> G["写入 access / refresh HttpOnly cookie"]
    H["登录页"] --> I["POST /api/auth/login"]
    I --> G
    G --> J["AuthProvider 调 /auth/me 恢复登录态"]
```

失败边界：

- SMTP 未配置：发码接口返回明确错误，不创建用户。
- access 过期：前端自动请求 `/api/auth/refresh`。
- refresh 失败：清理本地学习态并回 `/login`。

## 2. Notebook 入库与知识库状态

```mermaid
flowchart TD
    A["Profile / Chat 上传或添加 URL"] --> B["interfaces/api/upload.py"]
    A2["Profile 生成基础知识框架"] --> C["interfaces/api/subjects.py"]
    B --> D["application/ingest/service.py"]
    C --> E["application/notebooks/service.py"]
    D --> F["infrastructure/ingest/pdf.py / web.py"]
    E --> G["services/notebook_knowledge_base.py"]
    F --> G
    G --> H["services/rag/rag_service.py"]
    H --> I["PGVector collection learning_<subject_id>"]
    J["GET /api/notebooks/{id}/knowledge/status"] --> G
```

维护要点：

- URL/PDF/章节/题库向量 metadata 必须包含正确 `subject_id`、`doc_type`、`source_id`。
- 重复入库应走确定性 upsert，避免重复向量。
- Profile 卡片展示的资料数来自 knowledge status，失败时才 fallback 到 notebook `doc_count`。

## 3. 聊天与 RAG

```mermaid
flowchart TD
    A["POST /api/chat 或 /api/chat/sync"] --> B["interfaces/api/chat.py"]
    B --> C["application/chat/state_builder.py"]
    C --> D["application/chat/orchestrator_runtime.py"]
    D --> E["LearningOrchestratorGraph"]
    E --> F{"intent"}
    F -->|"concept / problem / review"| G["QAGraph"]
    F -->|"practice"| I["QuestionGenerationGraph"]
    F -->|"mastery"| H["MasteryEvaluationGraph"]
    F -->|"fallback"| J["response_composer"]
    G --> K["domains/qa/runtime.py"]
    K --> L["model profile + middleware"]
    L --> M["tool loop / grounding / fallback"]
    M --> N["services/tooling + services/rag"]
    N --> O["PGVector"]
    K --> P["answer_generation / postprocess"]
    P --> Z["response_composer"]
    I --> Z
    H --> Z
    J --> Z
    Z --> R["chat_sessions / user_memories / graph-era facts"]
    E -.空问题 / 子图异常.-> J
```

事实型 RAG 问题要求：

- 如果 notebook 检索命中事实，回答优先给直接结论。
- 如果当前 notebook 没检索到该事实，要明确说资料不足，再补一般解释。

## 4. 练习题包与提交作答

```mermaid
flowchart TD
    A["聊天 review 或 Practice 页请求题包"] --> B["QuestionGenerationGraph / PracticePackService"]
    B --> C["优先 question_bank_items / question_items"]
    C --> D{"题量足够?"}
    D -->|足够| E["返回题包"]
    D -->|不足| F["AI 生成补题 + quality gate"]
    F -->|失败或超时| G["fallback 补足请求题数"]
    E --> H["latest_quiz / practice 页面"]
    G --> H
    I["用户选择 A/B/C/D 提交"] --> J["POST /api/practice/attempts"]
    J --> K["domains/practice/attempts.py"]
    K --> L["practice_attempts"]
    K --> M["practice_attempt_finalization_jobs"]
    M --> N["attempts / learning_events"]
    N --> P["MasteryEvaluationGraph"]
    P --> Q["mastery_snapshots"]
    K --> O["user_memories 兼容更新"]
```

提交后前端必须展示：

- 你的答案
- 是否正确
- 正确答案
- 标准解析
- 当前选项为什么对/错

## 5. 知识点掌握度

```mermaid
flowchart LR
    A["聊天讲解完成"] --> B["LearningEvent"]
    C["做题提交"] --> D["attempt / scored signal"]
    B --> E["MasteryEvaluationGraph"]
    D --> E
    E --> F["mastery_snapshots"]
    F --> G["GET /api/users/{user_id}/knowledge/mastery"]
    G --> H["Dashboard / KnowledgePanel"]
```

V1 算法口径：

- 正确率提供主要分数。
- exposure 提供少量加成。
- 错题提供惩罚。
- `mastered >= 80`、`learning >= 50`、`weak < 50`。
- 旧 `user_knowledge_stats` 可作为历史兼容读取来源，不再是 graph-era mastery 的唯一事实表。

## 6. Profile / Dashboard 数据流

```mermaid
flowchart TD
    A["AuthProvider 提供 current user"] --> B["Profile"]
    A --> C["Dashboard"]
    B --> D["fetchNotebooks"]
    B --> E["fetchNotebookKnowledgeStatus"]
    B --> F["fetchUserProfile"]
    B --> G["fetchSessions"]
    B --> H["fetchPracticeRecommendations"]
    C --> I["fetchUserMemory"]
    C --> J["fetchKnowledgeMastery"]
```

维护要点：

- Profile 各请求独立加载，推荐题慢请求不能拖住 notebook 列表。
- Dashboard 学习记忆和掌握度独立加载，接口失败时展示缓存或空态。
- 页面主路径不使用 `default_user`。

## 7. LangSmith / MCP 观测边界

```mermaid
flowchart LR
    A["QA runtime"] --> B{"LangSmith enabled?"}
    B -->|是| C["记录 qa_agent.runtime / tool_loop / fallback"]
    B -->|否| D["无 tracing 模式"]
    A --> E{"MCP enabled + tool calling allowed?"}
    E -->|是| F["HTTP MCP web_search / web_read"]
    E -->|否| G["内部工具 + fallback"]
```

默认策略：

- LangSmith / MCP 都是可选能力。
- 配置缺失或服务不可用时 fail-open，不阻断主问答。
- MCP 不发送完整 notebook 正文、长期记忆或完整会话摘要。
