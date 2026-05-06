"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, BarChart3, BrainCircuit, Sparkles } from "lucide-react";
import BottomNav from "@/components/BottomNav";
import KnowledgePanel from "@/components/KnowledgePanel";
import { useAuth } from "@/components/AuthProvider";
import {
  fetchKnowledgeMastery,
  fetchUserMemory,
  type KnowledgeMastery,
  type Memory,
} from "@/lib/api";
import { loadStoredMemory, persistMemory } from "@/lib/learning-store";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

export default function DashboardPage() {
  const { user, isLoading } = useAuth();
  const userId = user?.id ?? "";
  const [memory, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [mastery, setMastery] = useState<KnowledgeMastery[]>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (isLoading || !userId) {
      return;
    }

    let isMounted = true;
    const cached = loadStoredMemory();
    setMemory(cached);
    setMastery([]);
    setLoadError("");

    void fetchUserMemory(userId)
      .then((remoteMemory) => {
        if (!isMounted) {
          return;
        }
        setMemory(remoteMemory);
        persistMemory(remoteMemory);
      })
      .catch((error) => {
        if (!isMounted) {
          return;
        }
        console.error("加载学习记忆失败:", error);
        setLoadError(
          error instanceof Error
            ? error.message
          : "学习记忆暂时加载失败，稍后可以重试。"
        );
      });

    void fetchKnowledgeMastery(userId)
      .then((items) => {
        if (isMounted) {
          setMastery(items);
        }
      })
      .catch((error) => {
        if (!isMounted) {
          return;
        }
        console.error("加载知识点掌握度失败:", error);
        setMastery([]);
      });

    return () => {
      isMounted = false;
    };
  }, [isLoading, userId]);

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-4">
        <div className="neo-card-secondary w-full p-5 text-center">
          <p className="neo-label">Dashboard</p>
          <p className="mt-3 text-lg font-black">正在恢复你的学习中心…</p>
        </div>
      </div>
    );
  }

  const totalErrors = Object.values(memory.error_count).reduce(
    (total, count) => total + count,
    0
  );

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-muted px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="neo-label">Dashboard</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight">学习中心</h1>
            <p className="mt-3 text-sm font-bold leading-relaxed">
              这里不是“好不好看”的报表，而是你最近到底卡在哪、强在哪。
            </p>
          </div>

          <span className="neo-badge rotate-3 bg-white">REPORT</span>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        <div className="space-y-4">
          {loadError ? (
            <section className="neo-card-accent p-4">
              <p className="neo-label">Memory</p>
              <p className="mt-2 text-sm font-black leading-relaxed">
                学习记忆暂时没有加载成功：{loadError}
              </p>
              <p className="mt-2 text-xs font-bold leading-relaxed">
                已先展示本地缓存，聊天和练习仍可继续使用。
              </p>
            </section>
          ) : null}

          <section className="grid grid-cols-2 gap-3">
            <div className="neo-card-secondary p-4">
              <p className="neo-label">Recent</p>
              <p className="mt-2 text-3xl font-black">
                {memory.recent_topics.length}
              </p>
            </div>

            <div className="neo-card-accent p-4">
              <p className="neo-label">Errors</p>
              <p className="mt-2 text-3xl font-black">{totalErrors}</p>
            </div>

            <div className="neo-card p-4">
              <p className="neo-label">Weak Points</p>
              <p className="mt-2 text-3xl font-black">{memory.weak_points.length}</p>
            </div>

            <div className="neo-card-muted p-4">
              <p className="neo-label">Last Session</p>
              <p className="mt-2 text-sm font-black leading-snug">
                {memory.last_session ? "已有记录" : "还没开始"}
              </p>
            </div>
          </section>

          <KnowledgePanel memory={memory} mastery={mastery} showReportLink={false} />

          <section className="neo-card-secondary p-4">
            <div className="flex items-center gap-2">
              <BarChart3 size={16} strokeWidth={2.8} />
              <p className="neo-label">Next Move</p>
            </div>

            <p className="mt-3 text-sm font-bold leading-relaxed">
              {memory.weak_points.length > 0
                ? `下一步最值得做的是：回到问答页，针对「${memory.weak_points[0]}」再让助手讲一遍，然后马上去刷题页练一次。`
                : "你还没有形成明显短板，建议挑一个新笔记本继续积累资料并开始提问。"}
            </p>

            <div className="mt-4 grid grid-cols-1 gap-3">
              <Link href="/chat" className="neo-button w-full justify-center">
                <BrainCircuit size={16} strokeWidth={2.8} />
                去问答页继续学
              </Link>

              <Link
                href="/practice"
                className="neo-button-ghost w-full justify-center"
              >
                <Sparkles size={16} strokeWidth={2.8} />
                去刷题页做题
                <ArrowRight size={16} strokeWidth={2.8} />
              </Link>
            </div>
          </section>
        </div>
      </main>

      <BottomNav />
    </div>
  );
}
