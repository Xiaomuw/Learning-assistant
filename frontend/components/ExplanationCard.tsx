"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Lightbulb,
  Link2,
  ListOrdered,
  type LucideIcon,
} from "lucide-react";

export interface Explanation {
  topic: string;
  thinking: string;
  steps: string[] | string;
  mistakes: string | string[];
  similar: string | string[];
}

interface ExplanationCardProps {
  explanation: Explanation;
}

interface SectionProps {
  title: string;
  icon: LucideIcon;
  background: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

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
        onClick={() => setIsOpen((value) => !value)}
        className={`flex w-full items-center justify-between border-[3px] border-neo-ink px-4 py-3 shadow-neo-sm ${background}`}
      >
        <span className="flex items-center gap-2 text-sm font-black uppercase tracking-[0.14em]">
          <Icon size={16} strokeWidth={2.8} />
          {title}
        </span>

        <ChevronDown
          size={18}
          strokeWidth={2.8}
          className={`transition-transform duration-100 ${
            isOpen ? "rotate-180" : ""
          }`}
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
}: ExplanationCardProps) {
  const steps = Array.isArray(explanation.steps)
    ? explanation.steps
    : explanation.steps
      ? [explanation.steps]
      : [];
  const mistakes = Array.isArray(explanation.mistakes)
    ? explanation.mistakes
    : explanation.mistakes
      ? [explanation.mistakes]
      : [];
  const similar = Array.isArray(explanation.similar)
    ? explanation.similar
    : explanation.similar
      ? [explanation.similar]
      : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="neo-badge -rotate-2 bg-neo-secondary">
          Topic
        </span>
        <div className="-rotate-1 border-[3px] border-neo-ink bg-neo-muted px-4 py-2 shadow-neo-sm">
          <p className="text-sm font-black uppercase tracking-[0.14em]">
            {explanation.topic || "知识点"}
          </p>
        </div>
      </div>

      {explanation.thinking && (
        <Section
          title="解题思路"
          icon={Lightbulb}
          background="bg-neo-secondary"
        >
          <p className="text-sm font-bold leading-relaxed whitespace-pre-wrap">
            {explanation.thinking}
          </p>
        </Section>
      )}

      {steps.length > 0 && (
        <Section
          title="分步讲解"
          icon={ListOrdered}
          background="bg-neo-muted"
        >
          <ol className="space-y-3">
            {steps.map((step, index) => (
              <li key={`${step}-${index}`} className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center border-[3px] border-neo-ink bg-neo-accent text-sm font-black shadow-neo-sm">
                  {index + 1}
                </span>
                <p className="pt-1 text-sm font-bold leading-relaxed">{step}</p>
              </li>
            ))}
          </ol>
        </Section>
      )}

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

      {similar.length > 0 && (
        <Section
          title="延伸知识点"
          icon={Link2}
          background="bg-neo-secondary"
          defaultOpen={false}
        >
          <div className="flex flex-wrap gap-2">
            {similar.map((item, index) => (
              <span
                key={`${item}-${index}`}
                className="inline-flex items-center rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 text-xs font-black uppercase tracking-[0.14em] shadow-neo-sm"
              >
                {item}
              </span>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
