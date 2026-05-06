"use client";

import { Bot, ChevronDown, Cpu, PlugZap, Sparkles } from "lucide-react";
import type { ModelConfig } from "@/lib/api";

interface ModelSelectorCardProps {
  config: ModelConfig | null;
  isLoading?: boolean;
  error?: string | null;
  isUpdating?: boolean;
  healthStatus?: "idle" | "checking" | "ok" | "error";
  healthMessage?: string | null;
  onChange: (modelId: string) => void;
  onRetry?: () => void;
  onTestHealth?: () => void;
}

export default function ModelSelectorCard({
  config,
  isLoading = false,
  error = null,
  isUpdating = false,
  healthStatus = "idle",
  healthMessage = null,
  onChange,
  onRetry,
  onTestHealth,
}: ModelSelectorCardProps) {
  const selectedModel = config?.available_models.find(
    (item) => item.id === config.current_model
  );
  const isSwitchingEnabled = config?.model_switching_enabled === true;
  const isModelLocked = !!config && !isSwitchingEnabled;
  const currentModelLabel = selectedModel?.label ?? config?.current_model ?? "加载中";
  const currentModelBadge = isSwitchingEnabled ? "可切换" : `${currentModelLabel} 主模型`;
  const healthTone =
    healthStatus === "ok"
      ? "bg-green-100"
      : healthStatus === "error"
        ? "bg-red-100"
        : "bg-white";

  return (
    <section className="neo-card overflow-hidden">
      <div className="border-b-[3px] border-neo-ink bg-neo-accent px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Bot size={16} strokeWidth={2.8} />
            <p className="neo-label">AI Engine</p>
          </div>
          <span className="neo-badge bg-white">{currentModelBadge}</span>
        </div>
        <p className="mt-2 text-lg font-black leading-tight">
          {currentModelLabel} 当前启用
        </p>
      </div>

      <div className="space-y-4 p-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <label className="block">
            <span className="neo-label">Chat Model</span>
            <div className="relative mt-2">
              <select
                value={config?.current_model ?? ""}
                onChange={(event) => onChange(event.target.value)}
                disabled={!config || isUpdating || isModelLocked}
                className="neo-input appearance-none pr-12 disabled:cursor-not-allowed disabled:bg-white/70"
              >
                {!config && (
                  <option value="">
                    {isLoading ? "加载模型中..." : "当前没有可用模型"}
                  </option>
                )}
                {config?.available_models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label} · {model.provider}
                  </option>
                ))}
              </select>
              <ChevronDown
                size={18}
                strokeWidth={2.8}
                className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2"
              />
            </div>
          </label>

          <div className="-rotate-2 border-[3px] border-neo-ink bg-neo-secondary px-4 py-3 shadow-neo-sm">
            <p className="neo-label">Family</p>
            <p className="mt-1 text-sm font-black">
              {selectedModel?.family ?? "加载中"}
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="border-[3px] border-neo-ink bg-white px-4 py-3 shadow-neo-sm">
            <div className="flex items-center gap-2">
              <Sparkles size={14} strokeWidth={2.8} />
              <p className="neo-label">Provider</p>
            </div>
            <p className="mt-2 text-base font-black">
              {selectedModel?.provider ?? (error ? "读取失败" : "未连接")}
            </p>
          </div>

          <div className="border-[3px] border-neo-ink bg-neo-muted px-4 py-3 shadow-neo-sm">
            <div className="flex items-center gap-2">
              <Cpu size={14} strokeWidth={2.8} />
              <p className="neo-label">Embedding</p>
            </div>
            <p className="mt-2 break-all text-sm font-black">
              {config?.embedding_model ?? (isLoading ? "加载中" : "未知")}
            </p>
          </div>
        </div>

        {error ? (
          <div className="space-y-3 border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
            <p className="text-sm font-bold leading-relaxed text-neo-ink/80">
              模型列表刚刚没有拉取成功：{error}
            </p>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="neo-button-ghost w-full justify-center bg-neo-bg"
              >
                重新连接模型列表
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm font-bold leading-relaxed text-neo-ink/80">
            {isSwitchingEnabled
              ? "当前可在后端开放的模型之间切换；切换前会由后端验证模型是否可用。"
              : `模型选择待开放，当前以后端选定的 ${currentModelLabel} 为主；备用模型只在后端自动兜底。`}
          </p>
        )}

        {onTestHealth && (
          <div className={`space-y-3 border-[3px] border-neo-ink p-4 shadow-neo-sm ${healthTone}`}>
            <button
              type="button"
              onClick={onTestHealth}
              disabled={healthStatus === "checking"}
              className="neo-button-ghost w-full justify-center bg-white disabled:cursor-wait disabled:opacity-70"
            >
              <PlugZap size={16} strokeWidth={2.8} />
              {healthStatus === "checking"
                ? `正在测试 ${currentModelLabel}...`
                : `测试 ${currentModelLabel} 连接`}
            </button>
            {healthMessage && (
              <p className="text-sm font-bold leading-relaxed text-neo-ink/80">
                {healthMessage}
              </p>
            )}
          </div>
        )}

        {isUpdating && (
          <div className="inline-flex items-center gap-2 border-[3px] border-neo-ink bg-neo-secondary px-3 py-2 text-xs font-black uppercase tracking-[0.16em] shadow-neo-sm">
            正在切换模型...
          </div>
        )}

        {!config && isLoading && !error && (
          <div className="inline-flex items-center gap-2 border-[3px] border-neo-ink bg-white px-3 py-2 text-xs font-black uppercase tracking-[0.16em] shadow-neo-sm">
            正在连接模型服务...
          </div>
        )}
      </div>
    </section>
  );
}
