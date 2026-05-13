# 代码审查报告（2026-05-10）

> 历史审查说明：本文基于 2026-05-10 当时的基线和未提交差异，保留为问题追溯材料，不代表当前工作树仍存在相同问题。

## 审查范围
- 基线：`4be431887e1f387a54dfc2ff93e1a940f91d6d2f`
- 范围：`backend`、`frontend`、`frontend-weapp`、`miniprogram`（按当前未提交变更和现有工作树差异）
- 结论口径：仅将外部网络/DNS/密钥/配额问题归为环境阻塞；其余按代码回归处理。

## 关键发现（按优先级）

### P1
1. `backend/app/persistence/repositories/graph_facts.py`
   - 函数 `_text` 在截断字符串时总是追加 `...`，当前实现是 `text[:max_length] + "..."`。
   - 当 `max_length` 恰好为 20（数据库中多个字段 `String(20)`，例如 `status/request_mode/source_type`）时，返回值长度会变成 23。
   - 场景：上游输入超长且被送到 `SqlGraphRunRepository`/`SqlPracticeAttempt` 等写入，可能触发 `character varying(20)` 约束错误，表现为数据库长度约束相关回归。
   - 修复建议：超长字符串截断时应保留省略号预算（例如 `limit = max(1, max_length - 3)`），或统一按 `max_length` 精确裁剪后再附加省略标记。

### P1
2. 后端服务启动与测试一致性问题（环境准备链）
   - 本次启动后端测试环境时，`source .env` 解析报 `command not found: Assistant`，说明当前默认 `.env` 文件含有未加引号/注释残片。
   - 该问题导致服务在本地启动阶段断链（即使代码逻辑可用），并会影响 CI/本地统一复现。
   - 修复建议：在仓库启动文档与 `.env` 示例中统一规范环境变量格式；`source` 使用前做轻量校验并在后续日志中给出明确字段提示。

### P2
3. 全量单测命令稳定性
   - 使用 `python -m unittest discover -s tests` 在当前工作树有 15 次 `ImportError: No module named 'backend'`。
   - 这会把“发现/导入阶段”当作错误计入，影响自动化通过率判定，建议将问题分类为测试链路可复现性问题。
   - 修复建议：固定测试命令入口（`-t`、`PYTHONPATH`、或 test 包边界）并补充一个最小 smoke 验证脚本，确保在干净环境稳定执行。

## 兼容性与架构核对
- 已确认：`/api/chat` 相关测试中未见 legacy workflow 回退入口恢复（对应测试文件仍有覆盖）。
- `LearningOrchestratorGraph` 分支与 `QAGraph/QuestionGenerationGraph/Mastery` 的职责边界在现有 graph 架构测试中仍有覆盖。
- Weapp 侧 API 路径与后端路由基本对齐（`/auth/wechat-mini/*`、`/subjects`、`/practice/*`、`/users/...`）。

## 建议
- 优先修复 P1-1 的字符串截断逻辑，再复跑 `unittest discover` 和 `make test-graphs`。
- 同步修复 `.env` 可读性与启动一致性后，再复跑 `/api/chat` 关键 API 冒烟。
