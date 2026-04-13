"use client";

import { Bot, ChevronDown, Cpu, Sparkles } from "lucide-react";
import type { ModelConfig } from "@/lib/api";

interface ModelSelectorCardProps {
  config: ModelConfig | null;
  isLoading?: boolean;
  error?: string | null;
  isUpdating?: boolean;
  onChange: (modelId: string) => void;
  onRetry?: () => void;
}

export default function ModelSelectorCard({
  config,
  isLoading = false,
  error = null,
  isUpdating = false,
  onChange,
  onRetry,
}: ModelSelectorCardProps) {
  const selectedModel = config?.available_models.find(
    (item) => item.id === config.current_model
  );

  return (
    <section className="neo-card overflow-hidden">
      <div className="border-b-[3px] border-neo-ink bg-neo-accent px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Bot size={16} strokeWidth={2.8} />
            <p className="neo-label">AI Engine</p>
          </div>
          <span className="neo-badge bg-white">
            Claude 已隐藏
          </span>
        </div>
        <p className="mt-2 text-lg font-black leading-tight">
          后台模型可切换
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
                disabled={!config || isUpdating}
                className="neo-input appearance-none pr-12"
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
            当前只展示非 Claude 模型，并按你的账号实际可用列表过滤；如果后续数据海洋开放 Gemini，这里会自动出现。
          </p>
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
