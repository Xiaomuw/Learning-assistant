"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Link2,
  type LucideIcon,
} from "lucide-react";

export interface Explanation {
  topic: string;
  thinking: string;
  steps: string[];
  mistakes: string;
  similar: string[];
}

interface ExplanationCardProps {
  explanation: Explanation;
  questionType?: string;
  onSuggestionClick?: (text: string) => void;
}

interface SectionProps {
  title: string;
  icon: LucideIcon;
  background: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

const SIMILAR_TITLE: Record<string, string> = {
  concept: "延伸知识点",
  problem: "相关题型",
  compare: "相近概念",
  application: "可迁移场景",
  review: "建议继续复习",
  mcq_problem: "相关考点",
  practice: "同类练习",
  smalltalk: "可以继续聊",
  meta: "功能探索",
};

function Section({
  title,
  icon: Icon,
  background,
  defaultOpen = true,
  children,
}: SectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="animate-stamp-in">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className={`flex w-full items-center justify-between border-[3px] border-neo-ink px-4 py-3 shadow-neo-sm ${background}`}
      >
        <span className="flex items-center gap-2 text-sm font-black uppercase tracking-[0.14em]">
          <Icon size={16} strokeWidth={2.8} />
          {title}
        </span>
        <ChevronDown
          size={18}
          strokeWidth={2.8}
          className={`transition-transform duration-100 ${isOpen ? "rotate-180" : ""}`}
        />
      </button>
      {isOpen && (
        <div className="border-x-4 border-b-[3px] border-neo-ink bg-white px-4 py-4 shadow-neo-sm">
          {children}
        </div>
      )}
    </div>
  );
}

export default function ExplanationCard({
  explanation,
  questionType = "concept",
  onSuggestionClick,
}: ExplanationCardProps) {
  const mistakes = explanation.mistakes ? [explanation.mistakes] : [];
  const similar = explanation.similar;

  const similarTitle = SIMILAR_TITLE[questionType] ?? "延伸知识点";

  return (
    <div className="space-y-3">
      {/* Topic badge */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="neo-badge -rotate-2 bg-neo-secondary">Topic</span>
        <div className="-rotate-1 border-[3px] border-neo-ink bg-neo-muted px-4 py-2 shadow-neo-sm">
          <p className="text-sm font-black uppercase tracking-[0.14em]">
            {explanation.topic || "知识点"}
          </p>
        </div>
      </div>

      {/* Mistakes */}
      {mistakes.length > 0 && (
        <Section
          title="易错点"
          icon={AlertTriangle}
          background="bg-neo-accent"
          defaultOpen={false}
        >
          <div className="space-y-2">
            {mistakes.map((mistake, index) => (
              <div
                key={`${mistake}-${index}`}
                className="border-[3px] border-neo-ink bg-neo-bg px-3 py-3 shadow-neo-sm"
              >
                <p className="text-sm font-bold leading-relaxed">{mistake}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Similar — 可点击触发追问 */}
      {similar.length > 0 && (
        <Section
          title={similarTitle}
          icon={Link2}
          background="bg-neo-secondary"
          defaultOpen={false}
        >
          <div className="flex flex-wrap gap-2">
            {similar.map((item, index) =>
              onSuggestionClick ? (
                <button
                  key={`${item}-${index}`}
                  type="button"
                  onClick={() => onSuggestionClick(item)}
                  className="inline-flex items-center rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 text-xs font-black uppercase tracking-[0.14em] shadow-neo-sm transition-all duration-100 hover:-translate-y-0.5 hover:bg-neo-accent active:translate-y-0"
                  title="点击追问"
                >
                  {item}
                </button>
              ) : (
                <span
                  key={`${item}-${index}`}
                  className="inline-flex items-center rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 text-xs font-black uppercase tracking-[0.14em] shadow-neo-sm"
                >
                  {item}
                </span>
              )
            )}
          </div>
          {onSuggestionClick && similar.length > 0 && (
            <p className="mt-2 text-[10px] font-bold text-neo-ink/50 uppercase tracking-widest">
              点击可直接追问
            </p>
          )}
        </Section>
      )}
    </div>
  );
}
