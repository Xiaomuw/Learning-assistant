"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import {
  AGENT_STYLE_PRESETS,
  type AgentStylePreset,
} from "@/lib/agent-style";
import type { UserProfile } from "@/lib/api";

interface AgentStyleEditorProps {
  profile: UserProfile | null;
  isSaving: boolean;
  title?: string;
  description?: string;
  submitLabel?: string;
  onSave: (payload: {
    agent_style_name: string;
    agent_style_prompt: string;
    onboarding_completed: boolean;
  }) => Promise<void> | void;
  onSkip?: () => Promise<void> | void;
}

export default function AgentStyleEditor({
  profile,
  isSaving,
  title = "Agent 风格设置",
  description = "这个设置是用户级的，会影响你所有笔记本里的回答口吻和扮演方式。",
  submitLabel = "保存风格",
  onSave,
  onSkip,
}: AgentStyleEditorProps) {
  const [styleName, setStyleName] = useState("");
  const [stylePrompt, setStylePrompt] = useState("");
  const [selectedPresetId, setSelectedPresetId] = useState<string>("");

  useEffect(() => {
    setStyleName(profile?.agent_style_name ?? "");
    setStylePrompt(profile?.agent_style_prompt ?? "");
    setSelectedPresetId("");
  }, [profile]);

  function applyPreset(preset: AgentStylePreset) {
    setSelectedPresetId(preset.id);
    setStyleName(preset.name);
    setStylePrompt(preset.prompt);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    await onSave({
      agent_style_name: styleName.trim(),
      agent_style_prompt: stylePrompt.trim(),
      onboarding_completed: true,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <p className="neo-label">Agent Persona</p>
        <h3 className="mt-2 text-xl font-black">{title}</h3>
        <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/75">
          {description}
        </p>
      </div>

      <div className="space-y-3">
        <p className="neo-label">快速预设</p>
        <div className="grid grid-cols-2 gap-3">
          {AGENT_STYLE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => applyPreset(preset)}
              className={`border-[3px] border-neo-ink px-3 py-3 text-left shadow-neo-sm transition-all duration-100 ease-linear hover:-translate-y-1 ${
                selectedPresetId === preset.id ? "bg-neo-accent" : "bg-white"
              }`}
            >
              <p className="text-sm font-black">{preset.name}</p>
              <p className="mt-1 text-xs font-bold leading-relaxed text-neo-ink/70">
                {preset.prompt.slice(0, 34)}...
              </p>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="neo-label mb-2 block">风格名称</label>
        <input
          type="text"
          value={styleName}
          onChange={(event) => setStyleName(event.target.value)}
          className="neo-input"
          placeholder="例如：温柔学伴 / 严格导师 / 面试官"
        />
      </div>

      <div>
        <label className="neo-label mb-2 block">风格提示词</label>
        <textarea
          value={stylePrompt}
          onChange={(event) => setStylePrompt(event.target.value)}
          className="neo-input min-h-[132px] resize-none text-sm leading-relaxed"
          placeholder="例如：你要像一个经验丰富但温柔的算法教练一样说话，先鼓励我，再用提问和类比引导我理解，不要一上来就给完整答案。"
        />
      </div>

      <div className="rounded-[1.25rem] border-[3px] border-neo-ink bg-neo-secondary p-4 shadow-neo-sm">
        <div className="flex items-center gap-2">
          <Sparkles size={16} strokeWidth={2.8} />
          <p className="neo-label">效果说明</p>
        </div>
        <p className="mt-2 text-sm font-bold leading-relaxed">
          这个设置只控制口吻、身份和表达方式，不会改变知识库来源，也不会影响模型设置。
        </p>
      </div>

      <div className="flex gap-3">
        {onSkip && (
          <button
            type="button"
            onClick={() => void onSkip()}
            disabled={isSaving}
            className="neo-button-ghost flex-1 justify-center bg-white"
          >
            稍后再说
          </button>
        )}

        <button
          type="submit"
          disabled={isSaving}
          className="neo-button flex-1 justify-center"
        >
          {isSaving ? (
            <Loader2 size={18} strokeWidth={2.8} className="animate-spin" />
          ) : (
            submitLabel
          )}
        </button>
      </div>
    </form>
  );
}
