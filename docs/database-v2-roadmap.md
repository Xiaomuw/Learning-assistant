# 学习助手数据库 V2 演进路线与风险说明

> 更新日期：2026-04-16  
> 适用范围：**基于当前现状结构做逐步规范化，不做一次性推倒重来**

> **历史参考说明**：这份路线图来自早期 MySQL / SQLite 阶段，部分“当前结构”描述已不是 2026-04-28 的运行事实。当前正式运行时已经收口为 PostgreSQL + PGVector；当前事实请优先看 [数据库设计](database-design.md) 和 [项目当前状态](project-current-status.md)。

这份文档不描述“当前已经有什么”，而是回答另外两个问题：

- 如果后面要把数据库做得更规范，先改什么，后改什么？
- 每一步会影响谁、风险在哪里、怎么验收？

当前数据库现状请先看：

- [数据库设计文档](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-design.md)
- [ER 图 / 表关系图](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-er.md)

## 1. 当前结构的优点与边界

### 当前优点

- 开发速度快，特别适合 Agent 输出结构还在演进的阶段
- 会话、题包、摘要等高层对象直接落 `JSON`，改动成本低
- MySQL 主用、SQLite 回退，便于本地开发和 Docker 运行
- `subject` 命名虽然偏旧，但已经和 notebook 产品语义建立了兼容层

### 当前边界

- 缺少显式外键，长期看一致性校验依赖应用层
- 多处 `JSON` 字段不利于统计分析和复杂筛选
- `practice_attempts` 适合积累事实，但当前索引还偏轻
- `user_memories` 更像聚合缓存，不是完全可追溯的事件事实

## 2. V2 目标

V2 的目标不是“追求最完美范式”，而是让数据库更适合下面这几类需求：

- 更稳定的题库导入与撤回
- 更可控的 notebook 删除与数据级联
- 更细粒度的做题统计、错题分析、推荐
- 更清晰的用户体系扩展
- 更便于后续接 OCR 题目、推荐系统与学习分析

## 3. 推荐迁移原则

### 原则 1：先补约束和索引，再拆 JSON

这是最稳的顺序。  
原因是：

- 外键和索引提升的是一致性与性能
- JSON 拆表提升的是建模清晰度
- 后者影响更大，应该在前者稳定后再动

### 原则 2：保持外部 API 稳定

本项目已经有：

- `/api/subjects`
- `/api/notebooks`
- `/api/chat*`
- `/api/practice/*`
- `/api/users/*`

数据库迁移不应该直接改变这些 API 语义。  
如果内部要重构字段或新建表，应优先在仓储层做兼容。

### 原则 3：保留 `subject` 兼容层，逐步靠拢 notebook

V2 也不建议马上把数据库表名从 `subjects` 改成 `notebooks`。  
更现实的做法是：

- 继续让产品层统一叫 notebook
- 数据层内部保留 `subject_id`
- 等迁移工具和兼容层都成熟后，再考虑物理改名

## 4. 推荐演进阶段

### 阶段 A：补外键与组合索引

#### 建议改动

优先补这些逻辑关系的物理外键：

- `chat_sessions.subject_id -> subjects.id`
- `question_bank_items.subject_id -> subjects.id`
- `practice_attempts.subject_id -> subjects.id`
- `practice_attempts.question_id -> question_bank_items.id`  
  说明：这个关系只能在题库题稳定存在时启用；对 AI 生成题需允许为空或走软关联

补这些高频组合索引：

- `chat_sessions(user_id, updated_at)`
- `practice_attempts(user_id, created_at)`
- `practice_attempts(user_id, knowledge_point, created_at)`
- `question_bank_items(subject_id, knowledge_point, difficulty, source_year)`

#### 收益

- 我的页最近会话、会话恢复、推荐题查询会更稳
- 做题统计速度提升明显
- notebook 删除时能更明确处理孤儿数据

#### 风险

- 历史脏数据可能导致补外键失败
- `practice_attempts.question_id` 目前包含 AI 题和题库题，不能简单强约束

#### 迁移前检查

建议先跑：

```sql
SELECT subject_id
FROM chat_sessions
WHERE subject_id NOT IN (SELECT id FROM subjects);
```

```sql
SELECT subject_id
FROM question_bank_items
WHERE subject_id NOT IN (SELECT id FROM subjects);
```

```sql
SELECT subject_id
FROM practice_attempts
WHERE subject_id NOT IN (SELECT id FROM subjects);
```

如果这些查询有结果，说明要先清脏数据。

### 阶段 B：题库导入规范化

#### 建议改动

给 `question_bank_items` 增加可选字段：

- `import_batch_id`
- `source_provider`
- `raw_source_path`
- `is_active`
- `imported_at`

#### 收益

- 可以知道一题是从哪一批导入来的
- 支持撤回某一批题库
- 支持不同来源混合导入而不失真

#### 风险

- 如果没有设计好批次语义，后面删除或回滚题库会很痛苦

### 阶段 C：做题统计从“结果缓存”走向“事实驱动”

#### 建议改动

继续保留 `practice_attempts` 作为事实表，但减少对 `user_memories.error_count` 的强依赖。

更推荐的方向是：

- `practice_attempts` 记录所有真实行为
- `user_memories` 只保存“为在线推荐做缓存的长期摘要”

也就是说：

- 真正可信的历史事实来自 `practice_attempts`
- `user_memories` 可以重建

#### 收益

- 数据更可追溯
- 更方便做日/周/月统计
- 后续加入学习报告会更稳

#### 风险

- 如果仍把 `user_memories` 当作唯一事实来源，后续修正历史会很困难

### 阶段 D：逐步拆分高频 JSON

#### 建议优先级

##### 优先保留不拆

- `chat_sessions.messages`
- `chat_sessions.session_memory`

原因：

- 这是 Agent 运行态产物
- 结构灵活度很重要
- 统计分析不是它们的第一目标

##### 优先考虑拆解

- `user_memories.error_count`
- `practice_attempts.question_snapshot`
- `question_bank_items.tags_json`

##### 最晚考虑拆解

- `chat_sessions.latest_quiz`

#### 一个更合理的演进方向

- 新增 `user_knowledge_stats`：按 `user_id + subject_id + knowledge_point` 聚合
- 新增 `question_bank_tags`：把标签拆成多行
- 如后续要做题目版本追踪，再考虑 `question_snapshot` 子表化

#### 风险

- JSON 拆解最容易诱发接口兼容问题
- 如果一次性大改，前后端和仓储层都要同步动，成本高

## 5. 推荐迁移顺序

建议顺序固定为：

1. 清理脏数据
2. 加组合索引
3. 加显式外键
4. 规范题库导入批次
5. 补统计聚合表
6. 按需要逐步拆 JSON

不建议顺序：

- 先把所有 JSON 拆光
- 先物理把 `subjects` 改名成 `notebooks`
- 先大改表，再去补 API 兼容

## 6. 风险清单

### 风险 1：历史脏数据阻塞外键迁移

表现：

- 老会话引用了不存在的 `subject_id`
- 老做题记录引用了不存在的 notebook

处理建议：

- 迁移前先跑完整性检查 SQL
- 需要时先补默认 notebook 或做孤儿数据迁移

### 风险 2：AI 题与题库题不能共享同一强约束

表现：

- `practice_attempts.question_id` 有时指向题库题
- 有时只是 AI 临时生成题的 ID

处理建议：

- `practice_attempts.question_id` 不要急着直接强 FK
- 可以先增加 `source_type` 分流
- 仅对 `source_type = 'question_bank'` 的记录做软校验或延迟迁移

### 风险 3：JSON 拆解引发前后端联动成本

表现：

- 前端依赖现有 `session_memory` / `latest_quiz` 结构
- 后端 Agent 输出也直接落 JSON

处理建议：

- 保持“运行态 JSON + 分析态事实表”并存
- 不要强迫运行链路立即范式化

## 7. 推荐验收方式

每一阶段迁移后都建议从 3 个层面验收：

### 结构验收

- 表是否成功创建/变更
- 索引是否存在
- 外键是否生效

### 行为验收

- 聊天是否还能正常写 `chat_sessions`
- 推荐题是否还能命中 `question_bank_items`
- 做题后 `practice_attempts` 是否仍能落库

### 业务验收

- 我的页最近会话是否正常
- 继续学习摘要是否正常
- 推荐题与练习页是否正常

## 8. 对当前项目最值得优先做的 3 件事

如果只做最小投入、最大收益的下一步，我建议优先做：

1. 给 `practice_attempts` 和 `question_bank_items` 补组合索引
2. 给题库导入加批次字段
3. 把 `user_memories` 定位明确成“长期摘要缓存”，不要当唯一事实来源

## 9. 配套文档

- [数据库设计文档](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-design.md)
- [ER 图 / 表关系图](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-er.md)
- [数据库样例数据与常用 SQL](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/database-examples.md)
- [现状兼容版 MySQL DDL 草案](/Users/xiaomu/Desktop/Python/Code/learning-assistant/docs/mysql-current-schema.sql)
