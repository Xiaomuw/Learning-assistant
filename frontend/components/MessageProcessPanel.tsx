"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  BrainCircuit,
  ChevronDown,
  CircleAlert,
  Search,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { MessageProcess, MessageProcessStage } from "@/lib/api";

interface MessageProcessPanelProps {
  process: MessageProcess;
  autoOpen?: boolean;
}

function getStageIcon(stage: MessageProcessStage) {
  switch (stage.key) {
    case "routing":
      return BrainCircuit;
    case "retrieval":
      return Search;
    case "guard":
      return ShieldCheck;
    case "tool_decision":
      return Wrench;
    case "execution":
      return Bot;
    case "answer":
      return Sparkles;
    default:
      return CircleAlert;
  }
}

function getStageBackground(status: MessageProcessStage["status"]) {
  if (status === "failed") {
    return "bg-neo-accent";
  }
  if (status === "running") {
    return "bg-neo-secondary";
  }
  return "bg-neo-muted";
}

function fallbackReasonLabel(reason?: string) {
  switch ((reason || "").trim()) {
    case "unauthorized_model":
      return "权限不足";
    case "primary_model_failed":
      return "主模型不可用";
    case "timeout":
      return "请求超时";
    case "connection":
      return "连接失败";
    default:
      return reason ? "模型不可用" : "";
  }
}

export default function MessageProcessPanel({
  process,
  autoOpen = false,
}: MessageProcessPanelProps) {
  const [isOpen, setIsOpen] = useState(autoOpen);

  useEffect(() => {
    setIsOpen(autoOpen);
  }, [autoOpen]);

  const stageCount = process.stages.length;
  const toolCount = process.toolCalls?.length ?? 0;
  const summary = useMemo(() => {
    if (process.currentStage?.trim()) {
      return process.currentStage.trim();
    }
    if (stageCount > 0) {
      return process.stages[stageCount - 1].label;
    }
    return "过程摘要";
  }, [process.currentStage, process.stages, stageCount]);

  return (
    <div className="mt-4 animate-stamp-in">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 border-[3px] border-neo-ink bg-neo-bg px-4 py-3 text-left shadow-neo-sm"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="neo-label">处理过程</span>
            <span className="neo-badge bg-white">{summary}</span>
          </div>
          <p className="mt-2 text-xs font-bold text-neo-ink/75">
            {stageCount} 个阶段 · {toolCount} 次工具调用
          </p>
        </div>

        <ChevronDown
          size={18}
          strokeWidth={2.8}
          className={`shrink-0 transition-transform duration-100 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {isOpen && (
        <div className="border-x-[3px] border-b-[3px] border-neo-ink bg-neo-bg px-5 py-5 shadow-neo-sm">
          <div className="flex flex-col gap-6">
            {/* 阶段列表 */}
            {process.stages.length > 0 && (
              <div className="flex flex-col gap-4">
                {process.stages.map((stage, idx) => {
                  const Icon = getStageIcon(stage);
                  const isLastStage = idx === process.stages.length - 1;
                  // If there is execution or tools after this, the last stage still needs a line
                  const hasNextSection = !!process.execution || toolCount > 0 || !!process.reasoningSummary;
                  const showLine = !isLastStage || hasNextSection;

                  return (
                    <div key={`${stage.key}-${stage.label}`} className="relative flex items-start gap-3">
                      {showLine && (
                        <div className="absolute bottom-[-16px] left-3 top-7 z-0 w-[2px] bg-neo-ink/20"></div>
                      )}
                      <div
                        className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-neo-ink ${getStageBackground(
                          stage.status,
                        )}`}
                      >
                        <Icon size={12} strokeWidth={2.8} />
                      </div>
                      <div className="flex flex-col pt-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold">{stage.label}</span>
                          {typeof stage.elapsed === "number" && (
                            <span className="text-xs font-bold text-neo-ink/50">
                              {stage.elapsed.toFixed(2)}s
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-sm font-medium text-neo-ink/80 leading-snug">
                          {stage.detail}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* 模型执行 */}
            {process.execution && (
              <div className="relative flex items-start gap-3">
                {(toolCount > 0 || !!process.reasoningSummary) && (
                  <div className="absolute bottom-[-16px] left-3 top-7 z-0 w-[2px] bg-neo-ink/20"></div>
                )}
                <div className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-neo-ink bg-neo-secondary">
                  <Bot size={12} strokeWidth={2.8} />
                </div>
                <div className="flex w-full flex-col pt-0.5">
                  <span className="mb-2 text-sm font-bold">模型执行</span>
                  <div className="flex flex-wrap gap-2">
                    {process.execution.mode && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.mode}
                      </span>
                    )}
                    {process.execution.modelFamily && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.modelFamily}
                      </span>
                    )}
                    {process.execution.modelProvider && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.modelProvider}
                      </span>
                    )}
                    {process.execution.modelId && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.modelId}
                      </span>
                    )}
                    {process.execution.streamingMode && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.streamingMode === "token"
                          ? "逐字流式"
                          : process.execution.streamingMode === "node"
                            ? "节点级流式"
                            : "非流式"}
                      </span>
                    )}
                    {typeof process.execution.modelLatencyMs === "number" && (
                      <span className="neo-badge bg-white px-2 py-0.5 text-[10px]">
                        {process.execution.modelLatencyMs}ms
                      </span>
                    )}
                    {process.execution.degraded && (
                      <span className="neo-badge bg-neo-accent px-2 py-0.5 text-[10px]">
                        已降级回退
                      </span>
                    )}
                  </div>
                  {process.execution.fallbackUsed && (
                    <div className="mt-3 border-[3px] border-neo-ink bg-neo-accent px-3 py-2 shadow-neo-sm">
                      <p className="text-xs font-black leading-relaxed text-neo-ink">
                        主模型{" "}
                        {process.execution.primaryModelId || "当前主模型"}{" "}
                        {fallbackReasonLabel(process.execution.fallbackReason)
                          ? `因${fallbackReasonLabel(process.execution.fallbackReason)}`
                          : "暂时不可用"}
                        ，已使用{" "}
                        {process.execution.fallbackModelId ||
                          process.execution.modelId ||
                          "备用模型"}{" "}
                        完成本轮回答。
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 工具调用 */}
            {toolCount > 0 && (
              <div className="relative flex items-start gap-3">
                {!!process.reasoningSummary && (
                  <div className="absolute bottom-[-16px] left-3 top-7 z-0 w-[2px] bg-neo-ink/20"></div>
                )}
                <div className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-neo-ink bg-white">
                  <Wrench size={12} strokeWidth={2.8} />
                </div>
                <div className="flex w-full flex-col pt-0.5">
                  <span className="mb-2 text-sm font-bold">工具调用 ({toolCount})</span>
                  <div className="flex flex-col gap-2">
                    {process.toolCalls?.map((toolCall, index) => (
                      <div
                        key={`${toolCall.name}-${index}`}
                        className="flex flex-col rounded border-2 border-neo-ink/20 bg-white/60 p-2.5"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-bold">{toolCall.label}</span>
                          <span
                            className={`rounded-sm border border-neo-ink px-1.5 py-0.5 text-[10px] font-bold ${
                              toolCall.success ? "bg-neo-secondary" : "bg-neo-accent"
                            }`}
                          >
                            {toolCall.success ? "成功" : "失败"}
                          </span>
                        </div>
                        <p className="mt-1.5 text-xs font-medium text-neo-ink/80">
                          {toolCall.argsSummary}
                        </p>
                        {typeof toolCall.docCount === "number" && (
                          <p className="mt-1 text-xs font-bold text-neo-ink/70">
                            命中 {toolCall.docCount} 条
                          </p>
                        )}
                        {toolCall.error && (
                          <p className="mt-1 text-xs font-bold text-neo-accent">
                            错误: {toolCall.error}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 决策摘要 */}
            {process.reasoningSummary && (
              <div className="relative mt-2 flex items-start gap-3 border-t-2 border-neo-ink/10 pt-4">
                <div className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-neo-ink bg-neo-muted">
                  <BrainCircuit size={12} strokeWidth={2.8} />
                </div>
                <div className="flex flex-col pt-0.5">
                  <span className="mb-1.5 text-sm font-bold">决策摘要</span>
                  <p className="whitespace-pre-wrap text-sm font-medium leading-relaxed text-neo-ink/80">
                    {process.reasoningSummary}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
