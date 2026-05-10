"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import {
  ArrowRight,
  BrainCircuit,
  NotebookPen,
  Target,
} from "lucide-react";
import ExplanationCard from "./ExplanationCard";
import MessageProcessPanel from "./MessageProcessPanel";
import { stripMarkdownArtifacts, type Message, type MessageProcess } from "@/lib/api";

interface ChatWindowProps {
  messages: Message[];
  isStreaming: boolean;
  onSuggestionClick?: (message: string) => void;
}

const SUGGESTIONS = [
  "什么是 HTTP？",
  "帮我复习 TCP 三次握手",
  "给我出两道数据库索引练习题",
];

function safeQuizHint(hint: string | undefined) {
  const raw = (hint ?? "").trim();
  if (!raw) {
    return "";
  }
  const cleaned = raw
    .replace(/正确答案是\s*[A-D]/gi, "")
    .replace(/选择\s*[A-D]\s*(?:并|，|,|。|\.)?/gi, "")
    .replace(/答案\s*[A-D]/gi, "")
    .trim();
  return cleaned || "先根据题干关键条件排除明显不符合的选项，再提交作答。";
}

function fallbackModelBadge(process?: MessageProcess) {
  const execution = process?.execution;
  if (!execution?.fallbackUsed) {
    return "";
  }
  const fallbackModel = execution.fallbackModelId || execution.modelId || "备用模型";
  return `已使用备用模型：${fallbackModel}`;
}

export default function ChatWindow({
  messages,
  isStreaming,
  onSuggestionClick,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  return (
    <div className="space-y-5">
      {messages.length === 0 && !isStreaming && (
        <section className="neo-card-secondary animate-stamp-in overflow-hidden p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="neo-label">H5 Learning Mode</p>
              <h2 className="mt-2 text-4xl font-black leading-none tracking-tight">
                随手一问
                <br />
                就开始学
              </h2>
            </div>
            <span className="neo-badge -rotate-3 animate-float-tag bg-white">
              START
            </span>
          </div>

          <div className="mt-4 -rotate-1 border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
            <div className="flex items-center gap-2">
              <BrainCircuit size={18} strokeWidth={2.8} />
              <p className="text-sm font-black uppercase tracking-[0.16em]">
                我能做什么
              </p>
            </div>
            <p className="mt-3 text-sm font-bold leading-relaxed">
              讲知识点、拆解思路、给你出题，还会记住你最近总是卡住的地方。
            </p>
          </div>

          <div className="mt-4 space-y-3">
            {SUGGESTIONS.map((suggestion, index) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onSuggestionClick?.(suggestion)}
                className={`flex w-full items-center justify-between border-[3px] border-neo-ink px-4 py-3 text-left font-black shadow-neo-sm transition-all duration-100 ease-linear hover:-translate-y-1 ${
                  index === 1 ? "bg-neo-muted" : "bg-white"
                }`}
              >
                <span className="text-sm">{suggestion}</span>
                <ArrowRight size={18} strokeWidth={2.8} />
              </button>
            ))}
          </div>
        </section>
      )}

      {messages.map((message, index) => {
        const isUser = message.role === "user";
        const visibleProcess = message.process;
        const fallbackBadge = fallbackModelBadge(visibleProcess);
        const plainContent = stripMarkdownArtifacts(message.content || "");
        const showPlainContent = Boolean(plainContent && !message.explanation);

        return (
          <article
            key={`${message.timestamp}-${index}`}
            className={`flex animate-stamp-in ${
              isUser ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={
                isUser
                  ? "max-w-[88%] border-[3px] border-neo-ink bg-neo-accent px-4 py-3 shadow-neo-sm"
                  : "w-full max-w-full neo-card bg-white p-4"
              }
            >
              {isUser ? (
                <div className="space-y-2">
                  <p className="neo-label">你刚刚问</p>
                  <p className="text-sm font-bold leading-relaxed whitespace-pre-wrap">
                    {plainContent}
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="neo-badge -rotate-2 bg-neo-secondary">
                      Coach
                    </span>
                    {message.process?.currentStage && (
                      <span className="neo-badge bg-white">
                        {message.process.currentStage}
                      </span>
                    )}
                    {fallbackBadge && (
                      <span className="neo-badge bg-neo-accent">
                        {fallbackBadge}
                      </span>
                    )}
                  </div>

                  {visibleProcess && (
                    <MessageProcessPanel
                      process={visibleProcess}
                    />
                  )}

                  {showPlainContent && (
                    <p className="mt-4 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                      {plainContent}
                    </p>
                  )}

                  {message.explanation && (
                    <div className="mt-4">
                      <ExplanationCard
                        explanation={message.explanation}
                        questionType={message.questionType ?? "concept"}
                        onSuggestionClick={onSuggestionClick}
                      />
                    </div>
                  )}

                  {message.quizClarification && (
                    <div className="mt-4">
                      <div className="neo-card-muted p-4">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p className="neo-label">Practice Setup</p>
                            <h3 className="mt-1 text-lg font-black">
                              {message.quizClarification.title}
                            </h3>
                          </div>
                          <span className="neo-badge bg-white">待选择</span>
                        </div>
                        <p className="mt-3 text-sm font-bold leading-relaxed">
                          {message.quizClarification.description}
                        </p>

                        <div className="mt-4 grid gap-2">
                          {message.quizClarification.recommended_options.map((option) => (
                            <button
                              key={`${option.source}-${option.value}`}
                              type="button"
                              onClick={() =>
                                onSuggestionClick?.(`围绕 ${option.value} 出 5 道单选题`)
                              }
                              className="flex w-full items-center justify-between border-[3px] border-neo-ink bg-white px-4 py-3 text-left text-sm font-black shadow-neo-sm transition-all duration-100 ease-linear hover:-translate-y-1"
                            >
                              <span>{option.label}</span>
                              <ArrowRight size={16} strokeWidth={2.8} />
                            </button>
                          ))}
                        </div>

                        <div className="mt-4 grid gap-3 sm:grid-cols-3">
                          <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                            <p className="neo-label">题型</p>
                            <p className="mt-1 text-sm font-black">单选题</p>
                          </div>
                          <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                            <p className="neo-label">难度</p>
                            <p className="mt-1 text-sm font-black">自适应</p>
                          </div>
                          <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                            <p className="neo-label">数量</p>
                            <p className="mt-1 text-sm font-black">5 道</p>
                          </div>
                        </div>

                        <button
                          type="button"
                          onClick={() =>
                            onSuggestionClick?.(
                              message.quizClarification?.custom_input_placeholder ??
                                "围绕 HashMap 出 5 道单选题"
                            )
                          }
                          className="neo-button-secondary mt-4 w-full justify-center"
                        >
                          {message.quizClarification.custom_input_placeholder}
                        </button>
                      </div>
                    </div>
                  )}

                  {message.quiz && message.quiz.length > 0 && (
                    <div className="mt-4 space-y-3">
                      <div className="neo-card-muted p-4">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p className="neo-label">Practice Pack</p>
                            <h3 className="mt-1 text-lg font-black">
                              练习题已经打包好了
                            </h3>
                          </div>
                          <Link
                            href="/practice"
                            className="neo-button-secondary px-3 py-2 text-[11px]"
                          >
                            去刷题
                          </Link>
                        </div>

                        <div className="mt-4 space-y-3">
                          {message.quiz.map((item, quizIndex) => (
                            <div
                              key={`${item.question}-${quizIndex}`}
                              className="rounded-[1.25rem] border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm"
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="neo-badge bg-neo-accent">
                                  {item.difficulty}
                                </span>
                                <span className="neo-badge bg-white">
                                  <Target size={12} strokeWidth={2.8} />
                                  {item.knowledge_point}
                                </span>
                                {item.source_type === "question_bank" && item.source_name ? (
                                  <span className="neo-badge bg-neo-secondary">
                                    {item.source_year
                                      ? `${item.source_name} · ${item.source_year}`
                                      : item.source_name}
                                  </span>
                                ) : (
                                  <span className="neo-badge bg-neo-secondary">AI 补题</span>
                                )}
                              </div>
                              <p className="mt-3 text-sm font-bold leading-relaxed">
                                {item.question}
                              </p>
                              {Array.isArray(item.options) && item.options.length > 0 ? (
                                <div className="mt-3 space-y-2">
                                  {item.options.map((option) => (
                                    <div
                                      key={`${item.question_id}-${option.key}`}
                                      className="rounded-[1rem] border-[3px] border-neo-ink bg-neo-bg p-3"
                                    >
                                      <div className="flex items-start gap-3">
                                        <span className="neo-badge bg-neo-secondary">{option.key}</span>
                                        <div className="flex-1">
                                          <p className="text-sm font-bold leading-relaxed">
                                            {option.text}
                                          </p>
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                              <p className="mt-3 text-xs font-black uppercase tracking-[0.16em] text-neo-ink/70">
                                进入练习页提交作答后，会显示正反馈、错因和完整解析。
                              </p>
                              {item.hint ? (
                                <div className="mt-3 border-[3px] border-neo-ink bg-neo-bg p-3">
                                  <div className="flex items-center gap-2">
                                    <NotebookPen size={14} strokeWidth={2.8} />
                                    <p className="neo-label">Hint</p>
                                  </div>
                                  <p className="mt-2 text-sm font-bold leading-relaxed">
                                    {safeQuizHint(item.hint)}
                                  </p>
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </article>
        );
      })}

      <div ref={bottomRef} />
    </div>
  );
}
