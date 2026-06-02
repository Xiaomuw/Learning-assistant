export default function HelpPage() {
  const itemClass =
    "neo-card border-2 sm:border-[3px] border-neo-ink p-3 sm:p-4 shadow-neo-xs sm:shadow-neo-sm";

  return (
    <main className="flex h-full flex-col bg-neo-bg px-3 sm:px-4 pt-3 sm:pt-4 pb-24">
      <section className={itemClass}>
        <p className="neo-label">H5 使用说明（普通用户视角）</p>
        <h1 className="mt-1 text-2xl sm:text-3xl font-black leading-tight">学习助手手册</h1>
        <p className="mt-2 text-[13px] sm:text-sm font-bold text-neo-ink/70">
          本页提供你在 Web 端（H5）最常用功能入口与操作提示。
        </p>
      </section>

      <section className={`${itemClass} mt-3 sm:mt-4`}>
        <p className="neo-label">核心页面</p>
        <ul className="mt-2 space-y-2 text-[13px] sm:text-sm font-bold leading-relaxed text-neo-ink/80">
          <li>
            <span className="font-black">/chat</span>
            ：发起提问、切换会话、上传资料、查看过程信息。
          </li>
          <li>
            <span className="font-black">/practice</span>
            ：查看最新题包并提交练习，支持答案解析与继续刷题。
          </li>
          <li>
            <span className="font-black">/dashboard</span>
            ：查看掌握度、学习建议与课程知识结构。
          </li>
          <li>
            <span className="font-black">/profile</span>
            ：个人信息、知识库状态、推荐练习与退出登录。
          </li>
          <li>
            <span className="font-black">/login /register</span>
            ：账号登录与注册。
          </li>
        </ul>
      </section>

      <section className={`${itemClass} mt-3 sm:mt-4`}>
        <p className="neo-label">提问建议</p>
        <ul className="mt-2 space-y-1 text-[13px] sm:text-sm font-bold text-neo-ink/80">
          <li>普通知识问答：直接输入问题即可，系统会自动判别是否需要联网。</li>
          <li>教学讲解：请明确说明你要理解的知识点、章节或错误点。</li>
          <li>出题需求：使用“出 X 道题”或“帮我生成题目”可进入练习出题流程。</li>
          <li>联网控制：聊天页可打开“联网”，适合查询时效性问题。</li>
          <li>追问来源：你可直接询问“你是怎么得到这个答案的？”查看工具使用说明。</li>
        </ul>
      </section>

      <section className={`${itemClass} mt-3 sm:mt-4`}>
        <p className="neo-label">常见异常</p>
        <ul className="mt-2 space-y-1 text-[13px] sm:text-sm font-bold text-neo-ink/80">
          <li>若会话长时间无响应，页面会给出可重试提示。</li>
          <li>若出现认证异常，请回到登录页重新登录。</li>
          <li>上传 PDF 后请等待资料入库完成，再发起相关问题。</li>
        </ul>
      </section>
    </main>
  );
}
