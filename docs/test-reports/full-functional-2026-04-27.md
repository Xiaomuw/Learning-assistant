# 全项目功能验收报告

日期：2026-04-27  
范围：Browser Use 端到端验收 + 必要 API 补充验证  
排除项：不完成邮箱验证码注册闭环；仅真实发送 1 封验证码邮件

## 结论

整体主流程可用：登录、登录态恢复、聊天 SSE、MCQ 判题、练习提交、知识点掌握度、Profile、模型配置、知识框架生成、PDF 入库、SMTP 发码均通过。

发现 3 个需要后续处理的问题：

1. URL 入库接口返回成功，但知识库状态未体现 URL 计数。
2. RAG 命中特定资料后，回答仍可能过于泛化，没有直接回答事实型问题。
3. 请求生成 2 道练习题时，外部模型超时后 fallback 只生成 1 道，用户侧没有明显“部分完成”提示。

另有 2 个测试工具/覆盖限制：

1. Browser Use 在点击退出登录时发生浏览器控制层超时；已用 API 和前端 redirect header 补充验证退出登录。
2. Browser Use 不便稳定操作系统文件选择器；PDF 上传已用同一后端接口做 API 验证。

## 环境与门禁

- 后端环境检查：通过，`scripts/check_environment.py` 显示启动级配置正常。
- 后端编译：通过，`python -m compileall app tests scripts`。
- 后端单测：通过，`Ran 86 tests`，`OK (skipped=5)`。
- Python 依赖：通过，`pip check` 无破损依赖。
- 前端 lint：通过，`npm run lint`。
- 前端 build：通过，`npm run build`。
- 模型连通性：通过，`chat_ok=True`、`embedding_ok=True`、`tool_calling=False`、`structured=False`。
- 后端服务：`http://127.0.0.1:8000/health` 正常。
- 前端服务：`http://127.0.0.1:3000/login` 正常。

## 测试数据

- 测试账号：`codex-test-e2e@example.com`
- 测试账号 ID：`c960faf3-2f13-42d1-836e-7c56cfe76da6`
- 新建 notebook：`codex-test-e2e-20260427`
- 复用 RAG notebook：`codex-test-20260425-rag-fast`
- SMTP 发码目标：用户指定测试邮箱（已在文档中脱敏）
- 临时 PDF：`/tmp/codex-test-e2e.pdf`

## 页面验收

### `/login`

结果：通过

- 登录测试账号成功。
- 登录后跳转 `/chat`。
- 刷新 `/chat` 后可恢复登录态。
- 未登录访问 `/chat` 返回 `307` 并跳转 `/login?next=%2Fchat`。

### `/register`

结果：部分通过

- 页面可访问，`GET /register` 返回 200。
- 真实调用 `/api/auth/register/send-code` 成功，返回“验证码已发送，请检查邮箱”。
- 未完成验证码输入与注册完成路径，因为本轮不等待人工验证码。

### `/chat`

结果：通过，有质量问题待优化

- 普通概念问答完成，SSE 没有卡死。
- DigitalOcean 当前模型不支持 tool calling / structured output 时，系统走 deterministic fallback，前端可正常展示。
- MCQ 文本判题成功识别为 `mcq_problem`，返回正确选项 C、解析和干扰项说明。
- RAG 问答完成且检索日志显示命中 5 条文档，但事实型回答质量存在问题，详见缺陷 D-002。

### `/practice`

结果：通过，有部分完成提示问题

- 初始空题包时页面展示空态和去问答页/我的页引导。
- 通过 review 问答生成题包后，刷题页展示单选题。
- 选择 C 并提交后，页面展示“回答正确”、你的答案、正确答案、标准解析和各选项理由。
- 提交后知识点掌握度更新。

### `/dashboard`

结果：通过

- 展示知识掌握度列表。
- 刚提交的「HTTP 默认端口」显示掌握度 70%、正确率 100%。
- 学习建议和下一步入口正常展示。

### `/profile`

结果：通过，有 URL 计数问题待处理

- 用户资料、推荐题、notebook 列表、知识库状态、模型配置均可展示。
- 新建 `codex-test-e2e-20260427` 成功。
- 生成基础知识框架成功，5 个章节入库，状态为可检索。
- 大模型设置可读，显示 `llama3.3-70b-instruct` 和 `all-mini-lm-l6-v2`。
- 修改密码表单可达；出于安全策略未代用户点击最终“更新密码”。

## 后端/API 补充验证

- `/api/auth/logout`：通过，返回“已退出登录”。
- `/api/auth/me`：退出并更新 cookie jar 后返回“请先登录”。
- `/api/upload`：通过，PDF 上传返回 `total_pages=1`、`total_chunks=1`。
- `/api/notebooks/codex-test-e2e-20260427/knowledge/status`：PDF 后返回 `doc_count=6`、`chapter_count=5`、`pdf_count=1`、`embedding_ready=true`。
- `/api/upload/urls`：接口返回 200，后端日志显示 upsert 1 段，但 status 未体现 URL，详见 D-001。

## 缺陷列表

### D-001 URL 入库成功后知识库状态未更新

严重级别：High  
页面/接口：Profile 编辑 notebook、`POST /api/upload/urls`、`GET /api/notebooks/{id}/knowledge/status`  
是否外部依赖：否

复现步骤：

1. 在 Profile 创建 `codex-test-e2e-20260427`。
2. 点击“生成基础内容”，确认章节入库后状态为 `章节 5`。
3. 通过编辑笔记本追加 URL：`https://example.com`。
4. 保存后观察 Profile 计数，并调用 knowledge status。

期望结果：

- URL 入库成功后，Profile 中该 notebook 应显示 `URL 1`。
- knowledge status 应显示 `url_count=1`，`doc_count` 应增加。

实际结果：

- 前端提示“已更新笔记本「codex-test-e2e-20260427」”。
- 后端日志显示 `POST /api/upload/urls` 返回 200，并记录“幂等入库完成: 1 段原文 → 1 个分块”。
- `GET /api/notebooks/codex-test-e2e-20260427/knowledge/status` 仍返回 `doc_count=5`、`url_count=0`。
- 后续 PDF 上传后状态为 `doc_count=6`、`pdf_count=1`，进一步说明 URL 计数没有生效。

建议后续排查：

- 检查 URL 入库 metadata 是否写入 `doc_type=url`。
- 检查 URL upsert 的 deterministic ID 是否与已有章节 chunk 冲突并覆盖。
- 检查 knowledge status 的统计过滤条件是否遗漏 URL metadata 格式。

### D-002 RAG 命中后事实型回答过于泛化

严重级别：Medium  
页面/接口：`/chat`、QA deterministic fallback  
是否外部依赖：部分依赖模型输出质量，但系统可通过 prompt/后处理改善

复现步骤：

1. 选择 `codex-test-20260425-rag-fast`。
2. 提问：“根据这个笔记本里的资料，HTTP 的默认端口是多少？”
3. 等待回答完成。

期望结果：

- 如果检索材料包含答案，应直接回答默认端口。
- 如果检索材料不包含答案，应明确说明“当前 notebook 没有检索到默认端口信息”。

实际结果：

- 后端日志显示检索命中 5 条，最高分约 0.78。
- 前端回答为“回顾笔记本中关于 HTTP 的基本信息”，分步讲解为“检查是否有关于默认端口的描述”，没有直接回答端口。

建议后续排查：

- QA fallback prompt 增加“事实型问题必须给出结论或明确说资料不足”的约束。
- 在 explanation fallback 中增加答案完整性校验。
- 对 RAG result 增加引用片段/来源展示，便于判断是检索缺失还是生成遗漏。

### D-003 请求 2 道题时只生成 1 道，缺少部分完成提示

严重级别：Medium  
页面/接口：`/chat` review -> `quiz_gen` -> `/practice`  
是否外部依赖：是，DigitalOcean 模型请求超时

复现步骤：

1. 在 `/chat` 提问：“帮我复习 HTTP，并给我生成两道单选练习题。”
2. 等待题包生成。
3. 进入 `/practice`。

期望结果：

- 生成 2 道题，或明确提示“外部模型超时，仅生成 1 道 fallback 题”。

实际结果：

- 前端显示“已准备 1 道练习题”。
- 后端日志显示 `AI 选择题生成失败: Request timed out.`，随后 fallback 生成 1 道题。
- 用户侧能继续做题，但没有明显说明这是部分完成。

建议后续排查：

- 给 `quiz_gen` 输出增加 `partial=true` / `degraded_reason`。
- 前端 Practice Pack 显示“模型超时，已先给你 1 道兜底题”。
- 如果用户明确要求 N 道题，fallback 可尝试生成 N 道确定性题。

## 测试限制与非缺陷记录

### T-001 Browser Use 点击退出登录时控制层超时

严重级别：Low  
类型：测试工具限制  
是否外部依赖：Browser Use

现象：

- Browser Use 点击 Profile 的“退出登录”按钮时，浏览器控制层返回 CDP 输入事件超时。
- 后续 Browser Use kernel reset 后仍无法重新打开新 tab。

补充验证：

- 用 API 调用 `/api/auth/logout` 成功。
- 更新 cookie jar 后 `/api/auth/me` 返回“请先登录”。
- 未登录访问前端 `/chat` 返回 `307`，跳转 `/login?next=%2Fchat`。

结论：

- 退出登录后端与前端 middleware 行为通过。
- Browser 端点击登出未完成，不作为产品缺陷。

### T-002 Browser Use 无法稳定自动化系统文件选择器

严重级别：Low  
类型：测试覆盖限制  
是否外部依赖：Browser Use

现象：

- Profile 的“上传资料”按钮会触发文件选择器，Browser Use 当前不适合稳定完成本机 PDF 选择。

补充验证：

- 使用同一登录态 cookie 调用 `/api/upload` 上传临时 PDF 成功。
- knowledge status 显示 `pdf_count=1`、`doc_count=6`。

结论：

- PDF 后端能力通过。
- 前端文件选择器的人工路径未在本轮自动化覆盖。

## 外部依赖观察

- SMTP：成功发送 1 封注册验证码邮件到用户指定测试邮箱（文档中不记录真实邮箱）。
- DigitalOcean 模型：chat 和 embedding 健康检查通过。
- DigitalOcean structured/tool：当前 profile 降级为不支持，不影响主流程。
- LangSmith：后端启动日志显示 tracing 已启用；本轮未进入 LangSmith Cloud UI 做人工确认。
- MCP：当前关闭，启动日志显示 `MCP_ENABLED=false`，不阻断主流程。

## 建议下次处理顺序

1. 优先修 D-001，保证 URL 入库后的 metadata、status、Profile 计数一致。
2. 优化 D-002，让 RAG fallback 对事实型问题必须给出答案或明确资料不足。
3. 优化 D-003，让题包 fallback 数量与用户请求一致，或明确展示部分完成原因。
4. 如需更完整前端自动化，可补 Playwright/Cypress 文件上传测试，而不是依赖 Browser Use 操作系统文件选择器。

## 修复记录

2026-04-27 已处理：

- D-001：向量写入改为目标 notebook collection 与 metadata `subject_id` 强一致，并补充 URL 入库契约测试；Profile 编辑弹窗追加 URL/PDF 后会刷新知识库状态。
- D-002：QA fallback 增加事实型问题 guard，命中 notebook 资料时优先给出直接事实答案，不再只输出泛化建议。
- D-003：题包生成失败时 fallback 会尽量补足请求题数，并将 fallback/partial/degraded reason 写入内部状态和聊天 process 说明。

验证结果：

- 后端 targeted tests 通过。
- 后端 `compileall` 通过。
- 后端全量 `unittest discover`：89 tests passed，5 skipped。
- 前端 `npm run lint` 与 `npm run build` 通过。
- `scripts/check_environment.py` 通过。
- `scripts/check_do_model_access.py` 在当前沙箱内因本机 PostgreSQL 访问被拦截，沙箱外重跑请求被使用额度限制拒绝；本轮未重新验证外部模型健康。

## 追加复测记录

2026-04-28 继续完成未测路径：

- `/chat` 普通问答通过，SSE 结束后输入框恢复可用。
- `/chat?notebook=codex-test-20260425-rag-fast` RAG 事实问答通过，针对“HTTP 的默认端口是多少？”直接返回 `80`。
- review 题包生成通过，DigitalOcean 出题超时时 fallback 补足 2 道题，并在聊天过程说明“其中 2 道使用备用题补齐”。
- `/practice` 最新题包展示通过，可选择选项并提交；提交后显示“回答正确”、你的答案、正确答案、解析和选项理由。
- `/profile` 发现并修复前端加载问题：notebook、个人资料、历史会话、推荐题拆成独立请求，避免推荐题慢请求拖住 notebook/资料统计渲染。
- `/dashboard` 发现并修复前端加载问题：学习记忆与知识点掌握度按稳定 `userId` 加载，并避免组件卸载后回写状态。
- 复测时 `npm run build` 会覆盖 Next dev server 的 `.next` 开发资源，导致已运行的 dev server 请求 `/_next/static/*` 变成 404；已通过重启前端 dev server 解决。这是测试环境问题，不是产品缺陷。
- Browser Use 在临时打开并关闭 API JSON 标签后失去活动 in-app browser pane，后续无法继续用 Browser Use 做视觉确认；已用后端 API、前端路由响应、lint/build 补齐验证。

追加验证结果：

- 前端 `npm run lint` 通过。
- 前端 `npm run build` 通过。
- 后端 `/health` 通过。
- 受保护前端路由在无 cookie 的 curl 请求下仍正确重定向到 `/login?next=...`。
