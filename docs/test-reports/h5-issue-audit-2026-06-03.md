# H5 全页面问题巡检记录

- 日期：2026-06-03
- 环境：`http://localhost:3003`
- 测试账号：`h5-user-test@example.com`
- 浏览器：Google Chrome，H5 容器宽度约 448px，视口 `1470 x 801`
- 范围：`/`、`/login`、`/register`、`/chat`、`/practice`、`/dashboard`、`/profile`、`/help`、底部导航
- 说明：本次只记录问题，不修复业务代码或样式代码；未产出截图。

## 结论

- P0/P1：未发现。
- P2：1 个，学习中心底部安全区 padding 在宽屏断点被覆盖，存在被底部导航遮挡的风险。
- P3：1 个，帮助页底部 spacing 与代码意图不一致。
- 登录、注册入口、问答空态、历史/新对话/联网开关、刷题页、我的页滚动到底部、底部导航 active 状态均通过。

## 问题清单

### H5-AUDIT-001

- ID：`H5-AUDIT-001`
- 页面/路径：`/dashboard`
- 严重程度：P2
- 现象：学习中心页面带固定底部导航，但主内容区域在当前宽屏 H5 视口下计算出的 `padding-bottom` 只有 `16px`。当前数据下最后一组卡片仍可见，但安全区不足，后续内容展开、数据变长或更小视口下有被底部导航遮挡、底部按钮难以点击的风险。
- 复现步骤：
  1. 使用测试账号登录 H5。
  2. 打开 `http://localhost:3003/dashboard`。
  3. 滚动到页面底部。
  4. 检查主内容区域与固定底部导航之间的底部留白。
- 实际结果：Chrome 巡检记录显示 `mainPaddingBottom = 16px`，底部导航高度约 `67px`，导航固定在视口底部。源码位置为 `frontend/app/dashboard/page.tsx:152`，当前 class 为 `py-3 sm:py-4 pb-24`。
- 期望结果：所有带 `BottomNav` 的页面在所有断点下都保留足够底部安全区，至少覆盖底部导航高度和安全区，例如 `96px` 或 `calc(104px + var(--safe-area-bottom))`。
- 可能原因：`sm:py-4` 在 `sm` 断点设置了上下 padding，覆盖了基础层的 `pb-24`，导致宽屏 H5 容器里实际底部 padding 退回到 `16px`。
- 建议修复方向：将上下 padding 拆开，例如使用 `pt-3 sm:pt-4 pb-[calc(104px+var(--safe-area-bottom))]`，或显式补充 `sm:pb-24`/`sm:pb-[calc(...)]`，避免断点规则覆盖底部安全区。

### H5-AUDIT-002

- ID：`H5-AUDIT-002`
- 页面/路径：`/help`
- 严重程度：P3
- 现象：帮助页没有底部导航，但页面主内容同样出现 `pb-24` 在宽屏断点失效的问题，实际 `padding-bottom` 为 `16px`。当前内容不长，没有遮挡，但 spacing 与代码意图不一致。
- 复现步骤：
  1. 打开 `http://localhost:3003/help`。
  2. 检查页面底部留白。
- 实际结果：Chrome 巡检记录显示 `mainPaddingBottom = 16px`。源码位置为 `frontend/app/help/page.tsx:6`，当前 class 为 `py-3 sm:py-4 pb-24`。
- 期望结果：如果帮助页需要 `pb-24`，宽屏断点也应保留该底部留白；如果不需要，应移除误导性的 `pb-24` 并统一 spacing 规则。
- 可能原因：与 `H5-AUDIT-001` 相同，`sm:py-4` 覆盖了基础层 `pb-24`。
- 建议修复方向：将 `py` 拆成 `pt`/`pb`，或明确删除不需要的 `pb-24`，保持页面 spacing 可预期。

## 通过项

- `/` 重定向：
  - 未登录态使用 `http://0.0.0.0:3003/` 验证，跳转到 `/login?next=%2F`。
  - 已登录态使用 `localhost`/`127.0.0.1` 验证，进入 `/chat`。
- `/login`：
  - 未登录态可见邮箱、密码输入框，`立即登录`、`创建新账号` 按钮可见。
  - 使用测试账号登录后跳转到 `/chat`。
  - 已登录态访问 `/login` 会进入 `/chat`，符合当前认证保护逻辑。
- `/register`：
  - 未登录态可见邮箱输入框、`发送验证码`、`去登录`。
  - `去登录` 按钮尺寸正常，记录到的按钮尺寸约 `111 x 42`。
  - 已登录态访问 `/register` 会进入 `/chat`，符合当前认证保护逻辑。
- `/chat`：
  - 顶部栏、团队信息、空态、快捷问题、输入栏和底部导航可见。
  - `历史` 点击后可见历史面板。
  - `联网` 点击后状态文本可变化。
  - `新对话` 点击后仍保持问答页空态。
  - 输入栏与底部导航之间约有 `16px` 间距，未发现互相遮挡。
- `/practice`：
  - 页面可加载题包和选项，空输入下 `提交作答` 为禁用状态。
  - 主内容 `padding-bottom` 记录为 `96px`，滚动到底部后提交按钮不被底部导航遮挡。
  - 底部导航 `刷题` active 状态正常。
- `/dashboard`：
  - 页面可加载统计、推荐练习、知识点卡片和知识结构分组。
  - `开始定向练习` 和知识点卡片可见。
  - 底部导航 `中心` active 状态正常。
  - 存在 `H5-AUDIT-001` 记录的底部安全区风险。
- `/profile`：
  - 页面可加载用户信息、统计、推荐练习、笔记本列表和 `退出登录`。
  - 滚动到底部后 `退出登录` 按钮仍在底部导航上方，`我的` 可正常滑到底部。
  - 主内容 `padding-bottom` 记录为 `104px`，底部导航 `我的` active 状态正常。
- `/help`：
  - 页面可加载 H5 使用说明、核心页面、提问建议、常见异常。
  - 不带底部导航，无遮挡。
  - 存在 `H5-AUDIT-002` 记录的 spacing 一致性问题。
- 底部导航：
  - `/chat`、`/practice`、`/dashboard`、`/profile` 均显示 `问答 / 刷题 / 中心 / 我的`。
  - 图标和文案风格已接近小程序导航；active 项以深色和选中底色区分。

## 验证命令

```bash
cd frontend
npm run lint
npm run build
```

- `npm run lint`：通过。
- `npm run build`：通过。
- 仍有既有 warning：
  - `frontend/app/dashboard/page.tsx:106`：`useEffect` 缺少 `loadDashboard` 依赖。
  - `frontend/app/profile/page.tsx:47`：`useEffect` 缺少 `loadProfile` 依赖。

## 剩余风险

- 本次没有真实提交注册验证码，避免触发邮件发送和创建额外账号。
- 本次没有提交刷题答案，避免改变测试账号练习记录。
- Chrome 自动化的 `fill` 曾受虚拟剪贴板限制影响，后续改用逐字输入完成验证；该限制不是 H5 应用问题。
