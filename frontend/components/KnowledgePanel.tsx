"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  Lightbulb,
  TrendingUp,
} from "lucide-react";
import type { KnowledgeMastery, Memory } from "@/lib/api";

interface KnowledgePanelProps {
  memory: Memory;
  mastery?: KnowledgeMastery[];
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
  mastery = [],
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
  const masteryItems = compact ? mastery.slice(0, 3) : mastery.slice(0, 6);
  const hasMasteryStats = masteryItems.length > 0;
  const weakMasteryItems = mastery
    .filter((item) => item.mastery_level === "weak")
    .slice(0, compact ? 3 : 6);

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
            <p className="mt-2 text-2xl font-black">
              {hasMasteryStats ? mastery.length : memory.recent_topics.length}
            </p>
          </div>
          <div className="border-[3px] border-neo-ink bg-neo-muted p-3 shadow-neo-sm">
            <p className="neo-label">Weak</p>
            <p className="mt-2 text-2xl font-black">
              {hasMasteryStats ? weakMasteryItems.length : memory.weak_points.length}
            </p>
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

          {hasMasteryStats ? (
            <div className="space-y-3">
              {masteryItems.map((item) => {
                const correctRate =
                  item.attempt_count > 0
                    ? Math.round((item.correct_count / item.attempt_count) * 100)
                    : 0;
                const levelLabel =
                  item.mastery_level === "mastered"
                    ? "掌握"
                    : item.mastery_level === "learning"
                      ? "学习中"
                      : "薄弱";
                const levelTone =
                  item.mastery_level === "mastered"
                    ? "bg-neo-secondary"
                    : item.mastery_level === "learning"
                      ? "bg-neo-muted"
                      : "bg-neo-accent";
                const practicedAt = item.last_practiced_at
                  ? new Date(item.last_practiced_at).toLocaleDateString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                    })
                  : "未练习";
                return (
                  <div
                    key={`${item.subject_id}:${item.knowledge_point}`}
                    className="border-[3px] border-neo-ink bg-neo-bg p-3 shadow-neo-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-black">{item.knowledge_point}</p>
                      <span className="neo-badge bg-white">{levelLabel}</span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs font-black uppercase tracking-[0.12em] text-neo-ink/70">
                      <span>掌握度 {Math.round(item.mastery_score)}%</span>
                      <span>
                        正确率 {item.attempt_count > 0 ? `${correctRate}%` : "待练习"}
                      </span>
                    </div>
                    <p className="mt-1 text-xs font-bold text-neo-ink/60">
                      最近练习：{practicedAt}
                    </p>

                    <div className="mt-3 h-4 border-[3px] border-neo-ink bg-white">
                      <div
                        className={`h-full border-r-[3px] border-neo-ink ${levelTone}`}
                        style={{ width: `${Math.max(4, Math.round(item.mastery_score))}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : recentTopics.length === 0 ? (
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

          {hasMasteryStats ? (
            weakMasteryItems.length === 0 ? (
              <div className="border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
                <p className="text-sm font-bold leading-relaxed">
                  当前统计里没有明显薄弱点，继续保持这个节奏。
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {weakMasteryItems.map((item) => (
                  <div
                    key={`${item.subject_id}:${item.knowledge_point}:weak`}
                    className="flex items-center justify-between gap-3 border-[3px] border-neo-ink bg-neo-accent px-3 py-3 shadow-neo-sm"
                  >
                    <p className="text-sm font-black">{item.knowledge_point}</p>
                    <span className="text-xs font-black uppercase tracking-[0.16em]">
                      错 {item.wrong_count} / 练 {item.attempt_count}
                    </span>
                  </div>
                ))}
              </div>
            )
          ) : weakPoints.length === 0 ? (
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
            {hasMasteryStats && weakMasteryItems.length > 0
              ? `优先回到「${weakMasteryItems[0].knowledge_point}」再刷一组题，先把正确率拉上来。`
              : memory.weak_points.length > 0
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
