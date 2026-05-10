# 全量功能回归测试报告（2026-05-10）

## 基本信息
- 日期：2026-05-10
- 分支：当前工作树（相对 `4be431887e1f387a54dfc2ff93e1a940f91d6d2f`）
- 目标：后端图能力、问答主链路、RAG、practice、前端构建与小程序目录结构做可上线级核验
- 判定口径：环境/DNS/外部服务问题单独归类为环境阻塞。

## 执行命令与结果

### 1. 自动化（按优先级）
- `backend/.venv313/bin/python scripts/check_environment.py`
  - 结果：通过；`LangSmith` DNS 不可达（环境告警）。
- `backend/.venv313/bin/python -m unittest discover -s tests`
  - 结果：`Ran 447 tests in 3.329s`
  - 结果：`FAILED (errors=15, skipped=12)`
  - 注：错误为 `ImportError: No module named 'backend'`（测试发现阶段），非功能路径直接失败；建议修复测试可执行性。
- `make test-graphs`
  - 结果：`192 tests, OK`
- `make eval-graphs`
  - 结果：`6 tests, 6 passed`
- `cd frontend && npm run lint`
  - 结果：No ESLint warnings/errors
- `cd frontend && npm run build`
  - 结果：Pass，11 pages 编译完成

### 2. 后端服务与 API 冒烟
- 目标端口：`127.0.0.1:8000`、`127.0.0.1:3000`
- 结果：启动后端时数据库连接不可达，`sqlalchemy.exc.OperationalError: connection is bad: connection to server at \"127.0.0.1:5432 failed: Operation not permitted`。
- 手工 `curl` 冒烟（`/health`, `/api/settings/model/health`, `/login`）
  - 结果：服务不可达（连接失败）
- 说明：当前环境中数据库端口未可达，导致完整 API 冒烟无法完成，需先恢复服务链路后复测。

### 3. 功能风险核验
- RAG 与知识库链路：
  - 本地日志显示 pgvector 检索在模型不可用时会回退关键词检索，属于降级路径；未执行完整端到端 API，因为后端服务未启动。
- 问答主链路：
  - 在可运行的单测环境中，`test-chat`/`qa` 路径存在模型不可用、DNS 不可达降级，返回错误信息可读。
  - `make test-graphs` 与 `eval-graphs` 通过率高，说明图路由与契约未出现阻断性回归。

### 4. 外部依赖阻塞
- 外部网络/DNS：`api.smith.langchain.com` 长期解析失败。
- 模型端：多处出现 `401 model not available`、`model_unavailable`、`model down`（日志级别多为 warning/error）。
- 数据库：本地服务不可达导致 API 冒烟受阻（启动级阻塞）。

## 通过率与风险
- 后端图测试通过率：192/192（test-graphs），6/6（eval-graphs）
- 代码静态与构建：前端 lint/build 通过
- 统一单测通过率：受 `unittest discover` 发现阶段错误影响，不可直接判为回归通过
- P0：当前未能完成 API 冒烟（数据库不可达）
- P1：模型/外部服务 DNS 与配额类阻塞、数据库不可达导致的“主链路无法冒烟”
- P2：发现阶段测试导入链路需修复以稳定化 CI 输出

## 结论
- 结论（当前环境）：
  - 代码核心图能力与构建层未暴露明显阻断性回归；
  - 但上游基础设施未就绪（数据库可达性、Env 文件启动一致性）与测试入口问题，暂不形成“直接可上线”结论。
- 下一步：
  1. 修复 `_text` 长度处理与测试启动方式；
  2. 使用标准 `DATABASE_URL` 环境、修正本地 `.env` 加载；
  3. 恢复数据库与模型链路后复测 `/api/health`、`/api/chat`、`/api/chat/sync`、`/api/practice/packs`。
