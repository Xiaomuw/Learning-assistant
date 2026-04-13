"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  Lightbulb,
  TrendingUp,
} from "lucide-react";
import type { Memory } from "@/lib/api";

interface KnowledgePanelProps {
  memory: Memory;
  compact?: boolean;
  showReportLink?: boolean;
  className?: string;
}

function getMasteryLevel(
  topic: string,
  errorCount: Record<string, number>
): { label: string; percent: number; tone: string } {
  const errors = errorCount[topic] ?? 0;

  if (errors === 0) {
    return { label: "掌握", percent: 100, tone: "bg-neo-secondary" };
  }

  if (errors <= 2) {
    return { label: "一般", percent: 60, tone: "bg-neo-muted" };
  }

  return { label: "薄弱", percent: 28, tone: "bg-neo-accent" };
}

export default function KnowledgePanel({
  memory,
  compact = false,
  showReportLink = true,
  className = "",
}: KnowledgePanelProps) {
  const recentTopics = compact
    ? memory.recent_topics.slice(0, 3)
    : memory.recent_topics.slice(0, 6);
  const weakPoints = compact
    ? memory.weak_points.slice(0, 3)
    : memory.weak_points.slice(0, 6);
  const totalErrors = Object.values(memory.error_count).reduce(
    (total, count) => total + count,
    0
  );

  return (
    <section className={`neo-card overflow-hidden bg-white ${className}`}>
      <div className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center border-[3px] border-neo-ink bg-white shadow-neo-sm">
            <BrainCircuit size={20} strokeWidth={2.8} />
          </div>
          <div>
            <p className="neo-label">Learning Radar</p>
            <h2 className="mt-1 text-xl font-black">知识掌握度</h2>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="border-[3px] border-neo-ink bg-neo-bg p-3 shadow-neo-sm">
            <p className="neo-label">Topics</p>
            <p className="mt-2 text-2xl font-black">{memory.recent_topics.length}</p>
          </div>
          <div className="border-[3px] border-neo-ink bg-neo-muted p-3 shadow-neo-sm">
            <p className="neo-label">Weak</p>
            <p className="mt-2 text-2xl font-black">{memory.weak_points.length}</p>
          </div>
          <div className="border-[3px] border-neo-ink bg-neo-accent p-3 shadow-neo-sm">
            <p className="neo-label">Errors</p>
            <p className="mt-2 text-2xl font-black">{totalErrors}</p>
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} strokeWidth={2.8} />
            <p className="neo-label">最近学习</p>
          </div>

          {recentTopics.length === 0 ? (
            <div className="border-[3px] border-neo-ink bg-neo-bg p-4 shadow-neo-sm">
              <p className="text-sm font-bold leading-relaxed">
                还没有学习记录，先去问一个问题吧。
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {recentTopics.map((topic) => {
                const mastery = getMasteryLevel(topic, memory.error_count);
                return (
                  <div
                    key={topic}
                    className="border-[3px] border-neo-ink bg-neo-bg p-3 shadow-neo-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-black">{topic}</p>
                      <span className="neo-badge bg-white">{mastery.label}</span>
                    </div>

                    <div className="mt-3 h-4 border-[3px] border-neo-ink bg-white">
                      <div
                        className={`h-full border-r-[3px] border-neo-ink ${mastery.tone}`}
                        style={{ width: `${mastery.percent}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} strokeWidth={2.8} />
            <p className="neo-label">需要加强</p>
          </div>

          {weakPoints.length === 0 ? (
            <div className="border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
              <p className="text-sm font-bold leading-relaxed">
                目前没有明显薄弱点，继续保持这个节奏。
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {weakPoints.map((point) => (
                <div
                  key={point}
                  className="flex items-center justify-between gap-3 border-[3px] border-neo-ink bg-neo-accent px-3 py-3 shadow-neo-sm"
                >
                  <p className="text-sm font-black">{point}</p>
                  <span className="text-xs font-black uppercase tracking-[0.16em]">
                    错 {memory.error_count[point] ?? 0} 次
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-[3px] border-neo-ink bg-neo-secondary p-4 shadow-neo-sm">
          <div className="flex items-center gap-2">
            <Lightbulb size={16} strokeWidth={2.8} />
            <p className="neo-label">学习建议</p>
          </div>
          <p className="mt-3 text-sm font-bold leading-relaxed">
            {memory.weak_points.length > 0
              ? `优先回到「${memory.weak_points[0]}」再刷一组题，先把同一知识点的错误次数压下来。`
              : "可以继续学新知识，或者主动让我出两道题检查掌握情况。"}
          </p>
        </div>

        {showReportLink && (
          <Link href="/dashboard" className="neo-button-ghost w-full justify-center">
            查看完整学习报告
            <ArrowRight size={16} strokeWidth={2.8} />
          </Link>
        )}
      </div>
    </section>
  );
}
