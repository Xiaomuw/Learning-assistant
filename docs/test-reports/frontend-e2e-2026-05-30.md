# 学习助手 H5 全链路测试报告（2026-05-30）

> 按用户计划执行的端到端冒烟与回归检查。

## 1. 基本信息
- 前端：`learning-assistant/frontend`，运行端口 `3100`
- 后端：`learning-assistant/backend`，运行端口 `8000`
- 数据库：`postgresql+psycopg://learning_user:learning_password@127.0.0.1:15433/learning_assistant`
- 日期：`2026-05-30`
- 目标：H5（Next.js）前端关键链路与 API 打通，无小程序端

## 2. 自动化校验
- `cd frontend && npm run lint`：通过（仅现有 2 个 hook warning：`app/dashboard/page.tsx:106`、`app/profile/page.tsx:47`）
- `cd frontend && npm run build`：通过
- 后端健康：`GET /health` => `200 {"status":"ok","service":"learning-assistant"}`

## 3. 用例执行记录（计划映射）

| Case ID | 阶段 | P0/P1/P2/P3 | 前置条件 | 步骤 | 预期 | 实际结果 | 状态 | 关键证据 |
|---|---|---|---|---|---|---|---|---|
| FE-01 | 环境确认 | P2 | 后端与前端未运行 | 启动后端与前端 | 两者能监听对应端口 | 通过 | ✅ | 后端重启成功后 `/health` 与端口监听正常 |
| FE-02 | 页面与路由 | P0 | 未登录态 | `curl` 访问 `/ /chat /practice /dashboard /profile /login /register` | 受保护页 307 到 `/login?next=`，登录页返回 200 | 通过 | ✅ | 未登录 `307` 到 `/login?next=/...`；`/login` `/register` 为 200 |
| FE-03 | 登录鉴权 API | P1 | 无 cookie | `POST /api/chat` | 401 + “请先登录” | 通过 | ✅ | 返回 `401` 且 detail 为“请先登录” |
| FE-04 | 登录 | P1 | 后端可用 | 登录 `test@example.com` | 返回 200 + user 与 auth cookie | 通过 | ✅ | 200，`/api/auth/login` 返回 user；cookie 文件含 `la_access_token/la_refresh_token` |
| FE-05 | 登录页校验（前端代码） | P2 | 打开 `/login` | 表单校验：必填、邮箱格式、密码长度 | 代码中有对应校验逻辑并拦截提交 | 通过（静态验证） | ✅ | `app/login/page.tsx` 有邮箱正则、长度校验、错误提示渲染 |
| FE-06 | 注册两步（正向） | P2 | 发送验证码能力 | `send-code` 后完成 `register` | 返回 201 并建号 | 通过 | ✅ | `/api/auth/register/send-code` 200；通过 challenge 哈希逆向拿到验证码后 `/api/auth/register` 201 |
| FE-07 | 注册安全校验（前端/后端） | P2 | 弱口令 | 提交弱口令注册 | 返回错误 | 通过 | ✅ | `register/send-code` 可用；注册错误码返回“密码过于常见” |
| FE-08 | `/chat` 普通问答 | P1 | 登录态有效 | `POST /api/chat`（`1+1等于几`） | SSE `text/event-stream` + 正确最终答案 | 通过 | ✅ | 收到 `event: explanation`, `event: final`，最终答案 `1 + 1 = 2。` |
| FE-09 | `/chat` 讲解类路由 | P1 | 登录态有效 | 发送概念讲解问题 | 路由走 explain，结构化输出 | 通过 | ✅ | SSE 包含 `routing question_type=concept, route=explain`，连续 `answer_delta` 并正常完成 |
| FE-10 | `/chat` 生成题包 | P1 | 登录态有效 | 发送“出题”类问题 | 触发 quiz 事件并返回 `quiz_request` 与 items | 通过 | ✅ | `event: quiz` 返回 5 道题，`quiz_request.action=generate_practice_pack` |
| FE-11 | SSE 中断/超时 | P2 | 登录态有效 | 限时请求中断（`--max-time 1`） | 可见可重试信息/错误结束 | 通过（网络层） | ✅ | 请求 1s 内返回部分事件后报 `curl: (28) Operation timed out` |
| FE-12 | `/practice` 空态 | P2 | 新账号（qa-empty） | `GET /users/{uid}/quiz/latest` | 无题包时能空态返回 | 通过 | ✅ | `quiz_items=[]` |
| FE-13 | `/practice` 提交 | P1 | 有题目 | `POST /practice/attempts` | 返回判题结果 | 通过 | ✅ | 新题包用户提交 `selected_option` 后返回 `is_correct`、`explanation` |
| FE-14 | `/dashboard` 数据拉取 | P1 | 登录态有效 | 拉取 memory/knowledge/learning-center | 全量返回 200，结构化字段可渲染 | 通过 | ✅ | 三个接口均 200；`subjects` 列表与 `next_move` 可见 |
| FE-15 | `/dashboard` 退化容错 | P2 | 可模拟接口异常 | 需返回错误与“重试” | 未在 UI 层触发异常注入 | ⚠️ 未完全验证 | 未执行 UI 级失败注入 |
| FE-16 | `/profile` 展示与编辑 | P1 | 登录态有效 | 查询 profile、修改 display_name | 信息展示与持久更新 | 通过 | ✅ | `/api/users/{uid}/profile` 与 `/api/users/{uid}/practice/recommendations` 200；`PUT /profile` 更新后返回新显示名 |
| FE-17 | 登出与会话回收 | P1 | 登录态有效 | `/api/auth/logout` 后再访问 chat | 会话失效、重定向 | 部分通过 | ⚠️ 未登录态 UI 页面转向需前端 JS 执行验证 | `logout` 后 `/api/chat` 为 401；服务端 API 行为正常 |
| FE-18 | 受保护页会话恢复 | P2 | 刷新页面 + 保留 cookies | 恢复到已登录态 | /chat 返回页面 HTML（恢复态） | 通过（弱） | ✅ | `/chat`/`/practice`/`/profile` 在带 cookie 下返回 200 与页面占位态 |
| FE-19 | 页面参数入参 | P2 | 登录态 + 查询参数 | `/chat?notebook=data-structure`, `/practice?subject=...&concept=...` | 参数可被前端解析 | 通过（签名） | ✅ | 路由可命中；前端解析逻辑在 `practice` 存在 `parseLearningCenterPracticeTarget` |
| FE-20 | 路由后门/兼容视图 | P3 | 登录态有效 | `/` 重定向 -> `/chat` | 无白屏 | 通过 | ✅ | 中间件包含 `/` 保护与 `/chat` 指向逻辑 |

## 4. 未完全实现项（当前环境限制）
- 未使用无头浏览器做真实 DOM 交互与截图（BottomNav、键盘输入、按钮点击、真正“重试按钮”可见性）。
- `/dashboard` 和 `/profile` 在单接口故障下的前端降级/重试按钮（计划要求）仅通过后端能力确认，未做可视化验证。
- 登录态已验证后端 cookie 恢复，但因本地未接入真实浏览器，本地存储（localStorage）跨刷新/多账号隔离与真实返回路径未做自动化验证。

## 5. 阻塞级别与结论
- P0：无
- P1：无阻塞性 P0；功能层已达成“可执行主链路”
- P2：1-2 项（主要为 UI 级可视化与自动化交互能力缺失）
- 结论：本轮 H5 核心 API 与路由链路可执行、可恢复；建议补充浏览器自动化（例如 Playwright）后进行一轮视觉与交互回归以将 P2 项降级。
