"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import {
  ArrowRight,
  BrainCircuit,
  NotebookPen,
  Sparkles,
  Target,
} from "lucide-react";
import ExplanationCard from "./ExplanationCard";
import type { Message } from "@/lib/api";

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
                    {message.content}
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="neo-badge -rotate-2 bg-neo-secondary">
                      Coach
                    </span>
                    <div className="flex items-center gap-2 text-xs font-black uppercase tracking-[0.16em]">
                      <Sparkles size={14} strokeWidth={2.8} />
                      流式讲解
                    </div>
                  </div>

                  <p className="mt-4 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                    {message.content || "正在组织讲解内容..."}
                  </p>

                  {message.explanation && (
                    <div className="mt-4">
                      <ExplanationCard explanation={message.explanation} />
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
                              className="border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm"
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="neo-badge bg-neo-accent">
                                  {item.difficulty}
                                </span>
                                <span className="neo-badge bg-white">
                                  <Target size={12} strokeWidth={2.8} />
                                  {item.knowledge_point}
                                </span>
                              </div>
                              <p className="mt-3 text-sm font-bold leading-relaxed">
                                {item.question}
                              </p>
                              <div className="mt-3 border-[3px] border-neo-ink bg-neo-bg p-3">
                                <div className="flex items-center gap-2">
                                  <NotebookPen size={14} strokeWidth={2.8} />
                                  <p className="neo-label">Hint</p>
                                </div>
                                <p className="mt-2 text-sm font-bold leading-relaxed">
                                  {item.hint}
                                </p>
                              </div>
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

      {isStreaming && (
        <div className="flex animate-stamp-in justify-start">
          <div className="flex items-center gap-2 border-[3px] border-neo-ink bg-neo-secondary px-4 py-3 shadow-neo-sm">
            <span className="h-3 w-3 bg-neo-ink animate-pulse-dot" />
            <span
              className="h-3 w-3 bg-neo-ink animate-pulse-dot"
              style={{ animationDelay: "0.15s" }}
            />
            <span
              className="h-3 w-3 bg-neo-ink animate-pulse-dot"
              style={{ animationDelay: "0.3s" }}
            />
            <span className="text-xs font-black uppercase tracking-[0.16em]">
              处理中
            </span>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
