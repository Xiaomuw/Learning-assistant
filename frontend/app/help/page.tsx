"use client";

import Link from "next/link";
import { ArrowLeft, BookOpen, BrainCircuit, MessageSquareQuote, Sparkles } from "lucide-react";
import BottomNav from "@/components/BottomNav";

export default function HelpPage() {
  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <Link href="/profile" className="neo-button-ghost px-3 py-2">
            <ArrowLeft size={16} strokeWidth={2.8} />
            返回我的
          </Link>
          <div className="text-right">
            <p className="neo-label">Help Center</p>
            <h1 className="mt-1 text-2xl font-black">系统介绍</h1>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        <div className="space-y-4">
          <section className="neo-card p-5">
            <p className="neo-label">What It Is</p>
            <h2 className="mt-2 text-2xl font-black">这是一个围绕笔记本学习的 AI 助手</h2>
            <p className="mt-3 text-sm font-bold leading-relaxed">
              你先把知识来源放进笔记本，再围绕这个笔记本问答、刷题、复盘。回答风格则跟着你这个用户走，不属于某个单独笔记本。
            </p>
          </section>

          <section className="neo-card-secondary p-5">
            <div className="flex items-center gap-2">
              <BookOpen size={18} strokeWidth={2.8} />
              <p className="neo-label">Notebook Flow</p>
            </div>
            <div className="mt-4 space-y-3">
              <div className="neo-card bg-white p-4">
                <p className="font-black">1. 选择系统默认库</p>
                <p className="mt-2 text-sm font-bold leading-relaxed">
                  数据结构与算法、计算机网络、计算机组成原理、操作系统原理等默认库由系统统一维护，新用户登录后即可直接选择学习。
                </p>
              </div>
              <div className="neo-card bg-white p-4">
                <p className="font-black">2. 补充我的资料</p>
                <p className="mt-2 text-sm font-bold leading-relaxed">
                  你可以上传 PDF 或添加 URL，作为仅自己可见的补充资料参与 RAG 检索。
                </p>
              </div>
              <div className="neo-card bg-white p-4">
                <p className="font-black">3. 围绕它连续学习</p>
                <p className="mt-2 text-sm font-bold leading-relaxed">
                  问答页负责讲解，刷题页负责巩固，学习中心负责回看薄弱点和最近主题。
                </p>
              </div>
            </div>
          </section>

          <section className="neo-card-muted p-5">
            <div className="flex items-center gap-2">
              <MessageSquareQuote size={18} strokeWidth={2.8} />
              <p className="neo-label">Style Setting</p>
            </div>
            <h2 className="mt-2 text-xl font-black">Agent 风格是用户级设置</h2>
            <p className="mt-3 text-sm font-bold leading-relaxed">
              你可以把助手设成面试官、教练、苏格拉底式导师或任何你习惯的口吻。这个设置会影响所有笔记本里的回答方式。
            </p>
          </section>

          <section className="neo-card-accent p-5">
            <div className="flex items-center gap-2">
              <BrainCircuit size={18} strokeWidth={2.8} />
              <p className="neo-label">Usage Tips</p>
            </div>
            <div className="mt-4 space-y-3 text-sm font-bold leading-relaxed">
              <p>如果你问的是“你是什么模型”“你能做什么”，系统会先识别为元问题，再直接回答，不会误走刷题或检索链路。</p>
              <p>第一次检索某些笔记本时可能会慢一点，因为向量模型会做冷启动准备。</p>
              <p>如果某轮请求超时，直接回到问答页重试即可，输入框会自动恢复。</p>
            </div>
          </section>

          <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Link href="/chat" className="neo-button w-full justify-center">
              <BrainCircuit size={16} strokeWidth={2.8} />
              去问答页
            </Link>
            <Link href="/practice" className="neo-button-secondary w-full justify-center">
              <Sparkles size={16} strokeWidth={2.8} />
              去刷题页
            </Link>
            <Link href="/profile" className="neo-button-ghost w-full justify-center bg-white">
              <BookOpen size={16} strokeWidth={2.8} />
              回到我的
            </Link>
          </section>
        </div>
      </main>

      <BottomNav />
    </div>
  );
}
