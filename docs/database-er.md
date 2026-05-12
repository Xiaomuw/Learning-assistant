# 学习助手数据库 ER 图

> 更新日期：2026-05-12  
> 说明：这是当前核心表族的**逻辑关系图**。生产 schema 以 Alembic migration 和 SQLAlchemy model 为准；部分关系已经有索引或外键约束，仍有兼容表通过应用层维护关系。

## 1. 逻辑关系图

```mermaid
erDiagram
    users ||--o{ auth_refresh_tokens : "user_id"
    users ||--o{ wechat_mini_identities : "user_id"
    users ||--|| user_profiles : "user_id"
    users ||--|| user_memories : "user_id"
    users ||--o{ chat_sessions : "user_id"
    users ||--o{ practice_attempts : "user_id"
    users ||--o{ learning_events : "user_id"
    users ||--o{ mastery_snapshots : "user_id"

    subjects ||--o{ chat_sessions : "logical subject_id"
    subjects ||--o{ question_bank_items : "logical subject_id"
    subjects ||--o{ practice_attempts : "logical subject_id"
    subjects ||--o{ kb_subject : "logical subject_id"

    kb_subject ||--o{ kb_chapter : "kb_subject_id"
    kb_chapter ||--o{ kb_topic : "kb_chapter_id"
    kb_topic ||--o{ kb_concept : "kb_topic_id"
    kb_concept ||--o{ kb_chunk : "kb_concept_id"

    chat_sessions ||--o{ practice_attempts : "logical session_id"
    question_bank_items ||--o{ practice_attempts : "logical question_id"

    graph_runs ||--o{ node_runs : "graph_run_id"
    graph_runs ||--o{ tool_runs : "graph_run_id"
    graph_runs ||--o{ learning_events : "graph_run_id"
    graph_runs ||--o{ attempts : "graph_run_id"
    learning_events ||--o{ mastery_snapshots : "event input"
    attempts ||--o{ mastery_snapshots : "attempt input"

    users {
        varchar id PK
        varchar email UK
        varchar password_hash
        datetime created_at
    }

    subjects {
        varchar id PK
        varchar name UK
        varchar icon
        text description
        datetime created_at
    }

    auth_refresh_tokens {
        varchar id PK
        varchar user_id IDX
        datetime expires_at
        datetime revoked_at
    }

    wechat_mini_identities {
        varchar id PK
        varchar user_id IDX
        varchar openid UK
        varchar unionid
    }

    email_verification_challenges {
        varchar id PK
        varchar email IDX
        varchar purpose
        datetime expires_at
    }

    user_memories {
        varchar user_id PK
        json weak_points
        json error_count
        json recent_topics
        varchar last_session
        datetime updated_at
    }

    user_profiles {
        varchar user_id PK
        varchar display_name
        varchar agent_style_name
        text agent_style_prompt
        boolean onboarding_completed
        datetime updated_at
    }

    chat_sessions {
        varchar id PK
        varchar user_id IDX
        varchar subject_id IDX
        varchar title
        json messages
        json latest_quiz
        json session_memory
        datetime created_at
        datetime updated_at
    }

    question_bank_items {
        varchar id PK
        varchar subject_id IDX
        varchar knowledge_point IDX
        text stem
        json options_json
        varchar correct_option
        text explanation
        json option_rationales_json
        varchar source_name
        int source_year
        varchar difficulty
        json tags_json
        datetime created_at
        datetime updated_at
    }

    kb_subject {
        varchar id PK
        varchar subject_id IDX
        varchar title
    }

    kb_chapter {
        varchar id PK
        varchar kb_subject_id IDX
        varchar title
    }

    kb_topic {
        varchar id PK
        varchar kb_chapter_id IDX
        varchar title
    }

    kb_concept {
        varchar id PK
        varchar kb_topic_id IDX
        varchar name
    }

    kb_chunk {
        varchar id PK
        varchar kb_concept_id IDX
        text content
    }

    practice_attempts {
        varchar id PK
        varchar user_id IDX
        varchar session_id IDX
        varchar subject_id IDX
        varchar question_id
        json question_snapshot
        varchar selected_option
        boolean is_correct
        varchar knowledge_point IDX
        varchar source_type
        datetime created_at
    }

    practice_attempt_finalization_jobs {
        varchar id PK
        varchar practice_attempt_id UK
        varchar status
        datetime created_at
        datetime processed_at
    }

    graph_runs {
        varchar id PK
        varchar graph_type IDX
        varchar graph_version
        varchar status
        json metadata_json
        datetime created_at
    }

    node_runs {
        varchar id PK
        varchar graph_run_id IDX
        varchar node_name IDX
        varchar status
    }

    tool_runs {
        varchar id PK
        varchar graph_run_id IDX
        varchar capability IDX
        varchar status
    }

    learning_events {
        varchar id PK
        varchar user_id IDX
        varchar graph_run_id IDX
        varchar event_type IDX
        json payload
        datetime created_at
    }

    attempts {
        varchar id PK
        varchar user_id IDX
        varchar concept_id IDX
        varchar source_type
        boolean is_correct
        datetime created_at
    }

    mastery_snapshots {
        varchar id PK
        varchar user_id IDX
        varchar concept_id IDX
        float p_mastery
        varchar mastery_level
        datetime updated_at
    }

    question_items {
        varchar id PK
        varchar primary_concept_id IDX
        json payload
        datetime created_at
    }

    concepts {
        varchar id PK
        varchar name IDX
        json aliases_json
        datetime created_at
    }

    app_settings {
        varchar key PK
        text value
        datetime updated_at
    }
```

## 2. 关系解释

### `subjects` 与业务实体

- `subjects` 是当前数据库层里的 notebook 兼容实现
- 一个 `subject/notebook` 可以拥有：
  - 多条聊天记录 `chat_sessions`
  - 多道真题/题库题 `question_bank_items`
  - 多条做题记录 `practice_attempts`

### `users` / `user_profiles` / `user_memories`

- `users` 是正式账号事实来源
- `user_profiles` 与 `user_memories` 通过同一个 `user_id` 组成用户的两块核心扩展数据：
  - `user_profiles`：昵称、风格、引导状态
  - `user_memories`：学习画像

### `chat_sessions`

- 是聊天事实主表
- 同时承担：
  - 历史消息存档
  - 最新题包存档
  - 会话摘要存档

### `question_bank_items`

- 是本地题库镜像表
- 用于承接导入的历年真题
- 当前推荐与混合出题都依赖它

### `practice_attempts`

- 是选择题提交事实表
- 每次用户作答都会落一条记录
- 与 `chat_sessions` 和 `question_bank_items` 保持兼容逻辑关联
- `practice_attempt_finalization_jobs` 负责把兼容提交幂等转成 graph-era `attempts / learning_events`

### Graph-era facts

- `graph_runs / node_runs / tool_runs` 记录 Graph、节点和工具运行摘要
- `learning_events` 是跨 Graph 学习事件事实
- `attempts` 是 graph-era 答题事实
- `mastery_snapshots` 是当前掌握度事实
- `question_items / concepts` 支撑 QuestionGenerationGraph 与 MasteryEvaluationGraph

### `app_settings`

- 属于系统级 KV 配置表
- 当前主要保存 `chat_model`

## 3. 当前数据库关系的现实约束

这张 ER 图需要结合当前实现理解：

- 它描述的是**逻辑关联**
- Alembic 已开始为核心账号、KB、graph-era facts 等路径补充索引和约束
- 因此：
  - 删除 `subject` 时，需要业务层决定是否清理关联会话和题库
  - 删除题库题时，不会自动影响历史 `practice_attempts`
  - 做题记录更多是“事件事实”，不是强一致引用

## 4. 推荐演进方向

后续如果数据库要更规范，可以按这个顺序演进：

1. 为高频查询补组合索引
2. 为 `subject / session / question` 补显式外键
3. 如统计需求增强，再逐步拆分高频 JSON 字段
4. 最后再决定是否物理迁移 `subject -> notebook`
