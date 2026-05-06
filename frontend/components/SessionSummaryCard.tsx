"use client";

import { ArrowRight, BrainCircuit, Goal, Layers3 } from "lucide-react";
import type { ChatSession, SessionMemory, Notebook } from "@/lib/api";

interface SessionSummaryCardProps {
  session: ChatSession;
  notebook?: Notebook | null;
  title?: string;
  compact?: boolean;
  className?: string;
  continueLabel?: string;
  onContinue?: () => void;
}

function getOpenLoops(memory?: SessionMemory) {
  return Array.isArray(memory?.openLoops) ? memory.openLoops.slice(0, 2) : [];
}

export function hasSessionSummary(memory?: SessionMemory) {
  return Boolean(
    memory &&
      (memory.summaryText ||
        memory.activeTopic ||
        memory.currentGoal ||
        memory.openLoops.length > 0)
  );
}

export default function SessionSummaryCard({
  session,
  notebook,
  title = "继续学习",
  compact = false,
  className = "",
  continueLabel = "继续学习",
  onContinue,
}: SessionSummaryCardProps) {
  if (!hasSessionSummary(session.sessionMemory)) {
    return null;
  }

  const memory = session.sessionMemory!;
  const openLoops = getOpenLoops(memory);
  const displayTopic = memory.activeTopic || session.title || "当前会话";
  const displayGoal = memory.currentGoal || "继续围绕这个主题深入学习";
  const displaySummary =
    memory.summaryText || "这轮会话已经形成了一个可继续追问的学习脉络。";

  return (
    <section
      className={`neo-card overflow-hidden bg-white ${compact ? "p-4" : "p-5"} ${className}`.trim()}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="neo-label">{title}</p>
          <h2
            className={`mt-2 font-black tracking-tight text-neo-ink ${
              compact ? "text-xl" : "text-2xl"
            }`}
          >
            {displayTopic}
          </h2>
          <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
            {notebook?.name ?? "辅助知识库"} · {session.messages.length} 条消息
          </p>
        </div>

        {onContinue && (
          <button
            type="button"
            onClick={onContinue}
            className="neo-button shrink-0 px-3 py-2 text-xs"
          >
            {continueLabel}
            <ArrowRight size={14} strokeWidth={2.8} />
          </button>
        )}
      </div>

      <div
        className={`mt-4 grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2"}`}
      >
        <div className="border-[3px] border-neo-ink bg-neo-secondary px-4 py-3 shadow-neo-sm">
          <div className="flex items-center gap-2">
            <Goal size={16} strokeWidth={2.8} />
            <span className="neo-label">当前目标</span>
          </div>
          <p className="mt-3 text-sm font-black leading-relaxed">{displayGoal}</p>
        </div>

        <div className="border-[3px] border-neo-ink bg-neo-muted px-4 py-3 shadow-neo-sm">
          <div className="flex items-center gap-2">
            <BrainCircuit size={16} strokeWidth={2.8} />
            <span className="neo-label">会话摘要</span>
          </div>
          <p className="mt-3 text-sm font-bold leading-relaxed text-neo-ink/80">
            {displaySummary}
          </p>
        </div>
      </div>

      <div className="mt-4 border-[3px] border-dashed border-neo-ink bg-neo-bg px-4 py-3">
        <div className="flex items-center gap-2">
          <Layers3 size={16} strokeWidth={2.8} />
          <span className="neo-label">待继续的问题</span>
        </div>
        {openLoops.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {openLoops.map((item) => (
              <span key={item} className="neo-badge bg-white text-left">
                {item}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm font-bold text-neo-ink/70">
            当前没有待继续的问题，可以直接围绕这个主题继续追问。
          </p>
        )}
      </div>
    </section>
  );
}
