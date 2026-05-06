# 学习助手数据库样例数据与常用 SQL

> 更新日期：2026-04-16  
> 口径：**基于当前已落地 ORM 结构整理**  
> 适用数据库：**MySQL 为主，SQLite 为开发回退**

> **历史参考说明**：这份文档保留早期 MySQL / SQLite 样例和 `default_user` 示例，主要用于理解旧数据形状。当前正式运行时是 PostgreSQL + PGVector，正式用户来自 `users` 表。当前事实请优先看 [数据库设计](database-design.md) 和 [项目当前状态](project-current-status.md)。

这份文档是数据库设计包的“实操附录”。  
如果 [数据库设计文档](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-design.md) 解决的是“表为什么这样设计”，这里解决的是：

- 真实数据大概长什么样
- 新同学第一次进库时应该看哪些字段
- 常见业务问题对应哪些 SQL

## 1. 使用说明

- 下方样例数据是**说明性样例**，字段口径与当前 ORM 保持一致，但值为示意值
- 产品层语义是 **notebook / 笔记本**，数据库内部仍保留 `subject_id`
- 部分 SQL 用到了 MySQL 的 JSON 读取能力；如果你在 SQLite 本地调试，需要改写 JSON 语法

## 2. 典型样例数据

### 2.1 `subjects`

```json
{
  "id": "database",
  "name": "数据库",
  "icon": "🗄️",
  "description": "索引、事务、SQL 优化、范式与存储结构",
  "created_at": "2026-04-16T09:30:00Z"
}
```

你第一次看这张表时，重点看：

- `id`：内部 notebook 标识
- `name`：前端展示名
- `description`：会参与知识库说明和检索上下文

---

### 2.2 `user_profiles`

```json
{
  "user_id": "default_user",
  "display_name": "学习者_7492",
  "agent_style_name": "苏格拉底教练",
  "agent_style_prompt": "你要像启发式教练一样说话，先提问、再引导、最后总结。",
  "onboarding_completed": true,
  "updated_at": "2026-04-16T10:12:00Z"
}
```

这张表体现的是：

- 用户是谁
- 想让 Agent 用什么风格说话
- 是否完成首次风格引导

---

### 2.3 `user_memories`

```json
{
  "user_id": "default_user",
  "weak_points": ["数据库索引", "事务隔离级别"],
  "error_count": {
    "数据库索引": 4,
    "事务隔离级别": 2
  },
  "recent_topics": ["MySQL 索引下推", "B+ 树", "MVCC"],
  "last_session": "session_db_001",
  "updated_at": "2026-04-16T10:18:00Z"
}
```

这张表重点看：

- `weak_points`：推荐和出题优先参考
- `error_count`：薄弱程度量化依据
- `recent_topics`：补充长期上下文

---

### 2.4 `chat_sessions`

```json
{
  "id": "session_db_001",
  "user_id": "default_user",
  "subject_id": "database",
  "title": "索引为什么能加速查询",
  "messages": [
    {
      "role": "user",
      "content": "什么是聚簇索引？",
      "timestamp": "2026-04-16T10:00:01Z"
    },
    {
      "role": "assistant",
      "content": "聚簇索引决定了数据行的物理组织方式。",
      "timestamp": "2026-04-16T10:00:06Z"
    }
  ],
  "latest_quiz": [
    {
      "question_id": "quiz_ai_001",
      "question": "关于 InnoDB 聚簇索引，下列说法正确的是？",
      "options": [
        {"key": "A", "text": "叶子节点保存完整数据行"},
        {"key": "B", "text": "叶子节点只保存主键"},
        {"key": "C", "text": "一个表可以有多个聚簇索引"},
        {"key": "D", "text": "聚簇索引与主键无关"}
      ],
      "correct_option": "A",
      "knowledge_point": "聚簇索引",
      "difficulty": "基础",
      "source_type": "ai_generated"
    }
  ],
  "session_memory": {
    "summary_text": "本会话集中在数据库索引原理，已讲到聚簇索引和 B+ 树。",
    "active_topic": "数据库索引",
    "current_goal": "理解聚簇索引与非聚簇索引差异",
    "open_loops": ["二级索引回表为什么会慢？"],
    "resolved_points": ["聚簇索引叶子节点保存整行数据"],
    "last_question_type": "concept",
    "last_updated_at": "2026-04-16T10:15:00Z"
  },
  "created_at": "2026-04-16T10:00:00Z",
  "updated_at": "2026-04-16T10:15:00Z"
}
```

这张表是当前数据库里最“胖”的一张：

- `messages`：短期记忆和历史恢复
- `latest_quiz`：最近一组题包
- `session_memory`：中期会话摘要

---

### 2.5 `question_bank_items`

```json
{
  "id": "bank_db_2024_001",
  "subject_id": "database",
  "knowledge_point": "数据库索引",
  "stem": "下列关于 B+ 树索引的说法，正确的是？",
  "options_json": [
    {"key": "A", "text": "叶子节点之间通常有序链表连接"},
    {"key": "B", "text": "所有键只出现在根节点"},
    {"key": "C", "text": "B+ 树不适合范围查询"},
    {"key": "D", "text": "内部节点保存完整数据行"}
  ],
  "correct_option": "A",
  "explanation": "B+ 树叶子节点按顺序链接，天然适合范围扫描。",
  "option_rationales_json": {
    "A": "正确，叶子节点顺序链表是范围查询高效的重要原因。",
    "B": "错误，键会分布在多层节点中。",
    "C": "错误，B+ 树非常适合范围查询。",
    "D": "错误，内部节点主要存索引键和子指针。"
  },
  "source_name": "2024 数据库真题",
  "source_year": 2024,
  "difficulty": "基础",
  "tags_json": ["真题", "索引", "B+树"],
  "created_at": "2026-04-16T09:40:00Z",
  "updated_at": "2026-04-16T09:40:00Z"
}
```

这张表是“题库镜像层”，当前推荐和出题都会优先查这里。

---

### 2.6 `practice_attempts`

```json
{
  "id": "attempt_001",
  "user_id": "default_user",
  "session_id": "session_db_001",
  "subject_id": "database",
  "question_id": "bank_db_2024_001",
  "question_snapshot": {
    "question": "下列关于 B+ 树索引的说法，正确的是？",
    "selected_option": "C"
  },
  "selected_option": "C",
  "is_correct": false,
  "knowledge_point": "数据库索引",
  "source_type": "question_bank",
  "created_at": "2026-04-16T10:20:00Z"
}
```

这张表是行为事实表，最适合做：

- 正确率统计
- 错题追溯
- 推荐题依据

---

### 2.7 `app_settings`

```json
{
  "key": "chat_model",
  "value": "openai-gpt-oss-20b",
  "updated_at": "2026-04-16T09:00:00Z"
}
```

当前它主要承担系统级 KV 配置，最重要的是当前聊天模型。

## 3. 常见 SQL 查询示例

下面 SQL 默认按 MySQL 8.x 语法书写。

### 3.1 查看所有 notebook（内部表名仍为 `subjects`）

```sql
SELECT id, name, icon, description, created_at
FROM subjects
ORDER BY created_at DESC;
```

### 3.2 查看某个用户最近更新的会话

```sql
SELECT id, subject_id, title, updated_at
FROM chat_sessions
WHERE user_id = 'default_user'
ORDER BY updated_at DESC
LIMIT 10;
```

适合排查：

- “用户最近到底聊了什么”
- “我的页为什么没显示最近会话”

### 3.3 查看某个会话的当前摘要重点

```sql
SELECT
  id,
  title,
  JSON_UNQUOTE(JSON_EXTRACT(session_memory, '$.active_topic')) AS active_topic,
  JSON_UNQUOTE(JSON_EXTRACT(session_memory, '$.current_goal')) AS current_goal,
  JSON_UNQUOTE(JSON_EXTRACT(session_memory, '$.summary_text')) AS summary_text
FROM chat_sessions
WHERE id = 'session_db_001';
```

适合排查：

- “继续学习摘要为什么没显示”
- “中期记忆有没有正常落库”

### 3.4 查看用户最近题包

```sql
SELECT id, title, latest_quiz, updated_at
FROM chat_sessions
WHERE user_id = 'default_user'
  AND JSON_LENGTH(latest_quiz) > 0
ORDER BY updated_at DESC
LIMIT 1;
```

### 3.5 查询某个知识点的真题

```sql
SELECT
  id,
  stem,
  correct_option,
  source_name,
  source_year,
  difficulty
FROM question_bank_items
WHERE subject_id = 'database'
  AND knowledge_point = '数据库索引'
ORDER BY source_year DESC, created_at DESC
LIMIT 20;
```

### 3.6 推荐题常用筛选：按 notebook + 知识点 + 难度

```sql
SELECT
  id,
  stem,
  difficulty,
  source_name,
  source_year
FROM question_bank_items
WHERE subject_id = 'database'
  AND knowledge_point IN ('数据库索引', '事务隔离级别')
  AND difficulty IN ('基础', '变式')
ORDER BY source_year DESC, created_at DESC
LIMIT 10;
```

### 3.7 查看某个用户最近 7 天做题正确率

```sql
SELECT
  COUNT(*) AS total_attempts,
  SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_attempts,
  ROUND(
    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100,
    2
  ) AS accuracy_rate
FROM practice_attempts
WHERE user_id = 'default_user'
  AND created_at >= NOW() - INTERVAL 7 DAY;
```

### 3.8 按知识点统计错误次数

```sql
SELECT
  knowledge_point,
  COUNT(*) AS total_attempts,
  SUM(CASE WHEN is_correct THEN 0 ELSE 1 END) AS wrong_attempts
FROM practice_attempts
WHERE user_id = 'default_user'
GROUP BY knowledge_point
ORDER BY wrong_attempts DESC, total_attempts DESC;
```

这个查询和 `user_memories.error_count` 的角色不同：

- `practice_attempts` 是原始事实
- `user_memories.error_count` 是聚合后的长期记忆

### 3.9 查看最近答错的真题

```sql
SELECT
  question_id,
  knowledge_point,
  selected_option,
  source_type,
  created_at
FROM practice_attempts
WHERE user_id = 'default_user'
  AND is_correct = FALSE
ORDER BY created_at DESC
LIMIT 20;
```

### 3.10 查看当前模型配置

```sql
SELECT `key`, `value`, updated_at
FROM app_settings
WHERE `key` = 'chat_model';
```

### 3.11 排查“用户风格为什么没生效”

```sql
SELECT
  user_id,
  display_name,
  agent_style_name,
  agent_style_prompt,
  onboarding_completed
FROM user_profiles
WHERE user_id = 'default_user';
```

### 3.12 查看长期记忆里的薄弱点和最近主题

```sql
SELECT
  user_id,
  weak_points,
  error_count,
  recent_topics,
  last_session,
  updated_at
FROM user_memories
WHERE user_id = 'default_user';
```

## 4. 典型排障路径

### 场景 1：我的页没有显示“继续学习摘要”

建议顺序：

1. 查 `chat_sessions` 最近有没有该用户会话
2. 确认 `session_memory` 是否为空
3. 确认 `updated_at` 是否比旧会话新

推荐 SQL：

```sql
SELECT
  id,
  title,
  updated_at,
  JSON_UNQUOTE(JSON_EXTRACT(session_memory, '$.active_topic')) AS active_topic,
  JSON_UNQUOTE(JSON_EXTRACT(session_memory, '$.current_goal')) AS current_goal
FROM chat_sessions
WHERE user_id = 'default_user'
ORDER BY updated_at DESC;
```

### 场景 2：推荐题总是命不中真题，只走 AI 补题

建议顺序：

1. 看 `question_bank_items` 里有没有这个 `subject_id`
2. 再看有没有匹配的 `knowledge_point`
3. 再看筛选条件是不是把难度或年份限制太死

### 场景 3：用户做了很多题，但长期记忆没更新

建议对照：

- `practice_attempts` 是否有新增事实
- `user_memories.error_count` 是否同步增长

如果前者有、后者没有，问题通常在应用层更新逻辑，不在表本身。

## 5. 新同学建议的读表顺序

如果你是第一次接手这个项目，建议按这个顺序理解数据库：

1. `subjects`
2. `chat_sessions`
3. `user_profiles`
4. `user_memories`
5. `question_bank_items`
6. `practice_attempts`
7. `app_settings`

这个顺序更贴近用户真实路径：

- 先选 notebook
- 再进入会话
- 会话里带题包和会话摘要
- 用户有自己的风格和长期学习画像
- 真题和做题记录为推荐与统计服务

## 6. 配套文档

- [数据库设计文档](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-design.md)
- [ER 图 / 表关系图](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-er.md)
- [现状兼容版 MySQL DDL 草案](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/mysql-current-schema.sql)
- [数据库 V2 演进路线与风险说明](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-v2-roadmap.md)
