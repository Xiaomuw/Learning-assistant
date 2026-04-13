"use client";

import { WandSparkles, X } from "lucide-react";
import AgentStyleEditor from "./AgentStyleEditor";
import type { UserProfile } from "@/lib/api";

interface AgentStyleOnboardingModalProps {
  profile: UserProfile | null;
  isSaving: boolean;
  onClose: () => void;
  onSave: (payload: {
    agent_style_name: string;
    agent_style_prompt: string;
    onboarding_completed: boolean;
  }) => Promise<void> | void;
  onSkip: () => Promise<void> | void;
}

export default function AgentStyleOnboardingModal({
  profile,
  isSaving,
  onClose,
  onSave,
  onSkip,
}: AgentStyleOnboardingModalProps) {
  return (
    <div className="absolute inset-0 z-[120] flex items-center justify-center bg-neo-bg/80 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-lg max-h-full flex-col overflow-hidden rounded-[2rem] border-[3px] border-neo-ink bg-white shadow-neo-lg">
        <div className="flex shrink-0 items-center justify-between border-b-[3px] border-neo-ink bg-neo-secondary px-6 py-4">
          <div className="flex items-center gap-3">
            <WandSparkles size={24} strokeWidth={2.8} />
            <div>
              <p className="neo-label">Welcome Setup</p>
              <h2 className="text-xl font-black">先定一下你的 Agent 风格</h2>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="transition-transform hover:-translate-y-1"
          >
            <X size={22} strokeWidth={2.8} />
          </button>
        </div>

        <div className="overflow-y-auto p-6">
          <AgentStyleEditor
            profile={profile}
            isSaving={isSaving}
            title="先设定你的专属说话风格"
            description="这是用户级设置，不属于某个笔记本。你可以让助手像面试官、教练、搭子，或者任何你喜欢的身份来和你说话。"
            submitLabel="保存并开始使用"
            onSave={onSave}
            onSkip={onSkip}
          />
        </div>
      </div>
    </div>
  );
}
