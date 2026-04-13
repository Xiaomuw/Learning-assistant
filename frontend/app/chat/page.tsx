"use client";

import { useEffect, useRef, useState } from "react";
import { Clock, Sparkles } from "lucide-react";
import ChatWindow from "@/components/ChatWindow";
import InputBar from "@/components/InputBar";
import SubjectSelector from "@/components/SubjectSelector";
import BottomNav from "@/components/BottomNav";
import AgentStyleOnboardingModal from "@/components/AgentStyleOnboardingModal";
import HistoryDrawer from "@/components/HistoryDrawer";
import {
  DEFAULT_USER_ID,
  deleteSession as deleteSessionRemote,
  fetchModelConfig,
  fetchSubjects,
  fetchSessions,
  fetchUserMemory,
  fetchUserProfile,
  generateKnowledgeBase,
  sendChatSSE,
  updateUserProfile,
  uploadPDFWithSubject,
  type Memory,
  type Message,
  type ModelConfig,
  type QuizItem,
  type Subject,
  type UserProfile,
} from "@/lib/api";
import {
  loadStoredMemory,
  loadStoredModelConfig,
  loadStoredSubjectId,
  loadStoredSessions,
  persistMemory,
  persistQuiz,
  persistStoredModelConfig,
  persistStoredSessions,
  persistStoredSubjectId,
  type ChatSession,
} from "@/lib/learning-store";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  concept: "概念理解",
  problem: "解题辅导",
  practice: "练习出题",
  review: "复习巩固",
  meta: "助手信息",
  smalltalk: "寒暄对话",
};

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState("general");
  const [isGenerating, setIsGenerating] = useState(false);
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [showStyleOnboarding, setShowStyleOnboarding] = useState(false);
  const [isSavingStyle, setIsSavingStyle] = useState(false);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [showHistory, setShowHistory] = useState(false);
  const activeStreamRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let isMounted = true;
    const requestedSubjectId =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("subject")
        : null;
    const requestedSessionId =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("session")
        : null;

    async function initializePage() {
      setMemory(loadStoredMemory());
      setSessions(loadStoredSessions());
      setModelConfig(loadStoredModelConfig());

      try {
        const [
          notebooks,
          remoteMemory,
          remoteSessions,
          remoteModelConfig,
          remoteProfile,
        ] = await Promise.all([
          fetchSubjects(),
          fetchUserMemory(DEFAULT_USER_ID).catch(() => null),
          fetchSessions(DEFAULT_USER_ID).catch(() => null),
          fetchModelConfig().catch(() => null),
          fetchUserProfile(DEFAULT_USER_ID).catch(() => null),
        ]);

        if (!isMounted) {
          return;
        }

        const storedSubjectId = loadStoredSubjectId();
        const fallbackId = notebooks.some((item) => item.id === requestedSubjectId)
          ? String(requestedSubjectId)
          : notebooks.some((item) => item.id === storedSubjectId)
            ? storedSubjectId
            : "general";

        setSubjects(notebooks);
        setSelectedSubjectId(fallbackId);
        persistStoredSubjectId(fallbackId);

        if (remoteMemory) {
          setMemory(remoteMemory);
          persistMemory(remoteMemory);
        }

        if (remoteSessions) {
          setSessions(remoteSessions);
          persistStoredSessions(remoteSessions);

          if (requestedSessionId) {
            const requestedSession = remoteSessions.find(
              (session) => session.id === requestedSessionId
            );

            if (requestedSession) {
              setCurrentSessionId(requestedSession.id);
              setMessages(requestedSession.messages);
              setSelectedSubjectId(requestedSession.subjectId);
              persistStoredSubjectId(requestedSession.subjectId);
            }
          }
        }

        if (remoteModelConfig) {
          setModelConfig(remoteModelConfig);
          persistStoredModelConfig(remoteModelConfig);
        }

        if (remoteProfile) {
          setUserProfile(remoteProfile);
          if (!remoteProfile.onboarding_completed) {
            setShowStyleOnboarding(true);
          }
        }
      } catch (error) {
        console.error("加载笔记本列表失败:", error);
      }
    }

    void initializePage();

    return () => {
      isMounted = false;
      activeStreamRef.current?.abort();
      activeStreamRef.current = null;
    };
  }, []);

  function updateLastAssistant(updater: (message: Message) => Message) {
    setMessages((previous) => {
      const next = [...previous];

      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === "assistant") {
          next[index] = updater(next[index]);
          break;
        }
      }

      return next;
    });
  }

  async function refreshSubjects() {
    const data = await fetchSubjects();
    setSubjects(data);
  }

  async function refreshSessions() {
    try {
      const remoteSessions = await fetchSessions(DEFAULT_USER_ID);
      setSessions(remoteSessions);
      persistStoredSessions(remoteSessions);
    } catch (error) {
      console.error("刷新聊天记录失败:", error);
    }
  }

  async function handleSaveStyle(payload: {
    agent_style_name: string;
    agent_style_prompt: string;
    onboarding_completed: boolean;
  }) {
    setIsSavingStyle(true);
    try {
      const nextProfile = await updateUserProfile(DEFAULT_USER_ID, payload);
      setUserProfile(nextProfile);
      setShowStyleOnboarding(false);
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: nextProfile.agent_style_name
            ? `已为你切到「${nextProfile.agent_style_name}」风格，后面的回答都会按这个口吻来。`
            : "已保存默认风格设置。",
          timestamp: Date.now(),
        },
      ]);
    } catch (error) {
      console.error("保存 Agent 风格失败:", error);
    } finally {
      setIsSavingStyle(false);
    }
  }

  async function handleSkipStyleSetup() {
    await handleSaveStyle({
      agent_style_name: "",
      agent_style_prompt: "",
      onboarding_completed: true,
    });
  }

  function handleSubjectSelect(subjectId: string) {
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;
    setIsStreaming(false);
    setSelectedSubjectId(subjectId);
    persistStoredSubjectId(subjectId);
    setMessages([]);
    setCurrentSessionId("");
  }

  function handleNewSession() {
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;
    setIsStreaming(false);
    setMessages([]);
    setCurrentSessionId("");
    setShowHistory(false);
  }

  async function handleGenerate(subjectId: string) {
    setIsGenerating(true);

    try {
      const result = await generateKnowledgeBase(subjectId);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `这个笔记本的基础内容已经生成完毕：${result.message}`,
          timestamp: Date.now(),
        },
      ]);

      await refreshSubjects();
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `基础内容生成失败：${
            error instanceof Error ? error.message : "未知错误"
          }`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleUpload(file: File) {
    setIsUploading(true);

    try {
      const result = await uploadPDFWithSubject(file, selectedSubjectId);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `资料已加入笔记本：${result.filename}，共 ${result.total_pages} 页，切成 ${result.total_chunks} 个知识分块。`,
          timestamp: Date.now(),
        },
      ]);

      await refreshSubjects();
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `上传失败：${
            error instanceof Error ? error.message : "未知错误"
          }`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsUploading(false);
    }
  }

  function handleSend(question: string) {
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;

    const sessionId = currentSessionId || crypto.randomUUID();
    const userMessage: Message = {
      role: "user",
      content: question,
      timestamp: Date.now(),
    };

    const assistantMessage: Message = {
      role: "assistant",
      content: "",
      timestamp: Date.now() + 1,
    };

    if (!currentSessionId) {
      setCurrentSessionId(sessionId);
    }

    setMessages((previous) => [...previous, userMessage, assistantMessage]);
    setIsStreaming(true);

    activeStreamRef.current = sendChatSSE(
      DEFAULT_USER_ID,
      question,
      (event) => {
        const data = event.data as Record<string, unknown>;

        switch (event.event) {
          case "status":
            updateLastAssistant((message) => ({
              ...message,
              content:
                typeof data.message === "string"
                  ? data.message
                  : "已连接学习引擎，正在处理你的问题。",
            }));
            break;

          case "routing":
            updateLastAssistant((message) => ({
              ...message,
              content: `已识别问题类型：${
                QUESTION_TYPE_LABELS[String(data.question_type ?? "concept")] ??
                String(data.question_type ?? "concept")
              }`,
            }));
            break;

          case "retrieval":
            updateLastAssistant((message) => ({
              ...message,
              content: `笔记本命中了 ${String(data.doc_count ?? 0)} 条内容，开始整理讲解。`,
            }));
            break;

          case "explanation": {
            const explanation =
              data.explanation as Message["explanation"] | undefined;
            const finalAnswer =
              typeof data.final_answer === "string" ? data.final_answer : "";

            updateLastAssistant((message) => ({
              ...message,
              content: explanation?.thinking || finalAnswer || "讲解已经准备好了。",
              explanation,
            }));
            break;
          }

          case "quiz": {
            const quizItems: QuizItem[] = Array.isArray(data.quiz_items)
              ? (data.quiz_items as QuizItem[])
              : [];
            const finalAnswer =
              typeof data.final_answer === "string" ? data.final_answer : "";

            if (quizItems.length > 0) {
              persistQuiz(quizItems);
            }

            updateLastAssistant((message) => ({
              ...message,
              content:
                finalAnswer ||
                message.content ||
                "我顺手帮你准备了一组练习题，去刷题页就能接着做。",
              quiz: quizItems.length > 0 ? quizItems : undefined,
            }));
            break;
          }

          case "memory": {
            if (!data.memory) {
              break;
            }

            const nextMemory = data.memory as Memory;
            setMemory(nextMemory);
            persistMemory(nextMemory);
            break;
          }

          case "error":
            updateLastAssistant((message) => ({
              ...message,
              content: `出错了：${String(
                data.error ?? "未知错误"
              )}。你可以直接再发一次问题。`,
            }));
            activeStreamRef.current = null;
            setIsStreaming(false);
            break;

          default:
            break;
        }
      },
      () => {
        updateLastAssistant((message) => ({
          ...message,
          content: message.content || "这轮学习已经处理完成。",
        }));
        activeStreamRef.current = null;
        setIsStreaming(false);
        void refreshSessions();
      },
      (error) => {
        updateLastAssistant((message) => ({
          ...message,
          content: `连接失败：${error.message}`,
        }));
        activeStreamRef.current = null;
        setIsStreaming(false);
      },
      {
        subjectId: selectedSubjectId,
        sessionId,
        idleTimeoutMs: 45000,
      }
    );
  }

  const selectedSubject = subjects.find(
    (subject) => subject.id === selectedSubjectId
  );

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="neo-label">Notebook Tutor</p>
            <h1 className="mt-2 inline-block -rotate-1 border-[3px] border-neo-ink bg-white px-4 py-2 text-3xl font-black tracking-tight shadow-neo-sm">
              学习助手
            </h1>
            <p className="mt-3 max-w-xs text-sm font-bold leading-relaxed">
              围绕你的笔记本来学，还会记住你卡住的地方。
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowHistory(true)}
              className="group flex flex-col items-center gap-1 transition-transform hover:-translate-y-1"
            >
              <div className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border-[3px] border-neo-ink bg-white shadow-neo-sm">
                <Clock size={18} strokeWidth={2.8} className="text-neo-ink" />
              </div>
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-6">
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <SubjectSelector
                subjects={subjects}
                selectedId={selectedSubjectId}
                onSelect={handleSubjectSelect}
                onGenerate={handleGenerate}
                isGenerating={isGenerating}
              />
            </div>
          </div>

          {userProfile?.agent_style_name && (
            <div className="-rotate-1 inline-flex max-w-full items-center gap-2 border-[3px] border-neo-ink bg-white px-4 py-2 shadow-neo-sm">
              <span className="neo-label">当前风格</span>
              <span className="truncate text-sm font-black">
                {userProfile.agent_style_name}
              </span>
            </div>
          )}

          {modelConfig && (
            <div className="flex items-center justify-between rounded-[1rem] border-[3px] border-neo-ink bg-neo-muted px-4 py-2 shadow-neo-sm">
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded-full border-2 border-neo-ink bg-green-500 animate-pulse" />
                <span className="text-xs font-black uppercase tracking-widest text-neo-ink">
                  {modelConfig.current_model}
                </span>
              </div>
              <span className="text-xs font-bold text-neo-ink/70">服务在线</span>
            </div>
          )}

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Sparkles size={16} strokeWidth={2.8} />
              <p className="neo-label">Notebook Feed</p>
            </div>

            <ChatWindow
              messages={messages}
              isStreaming={isStreaming}
              onSuggestionClick={handleSend}
            />
          </section>
        </div>
      </main>

      <div className="sticky bottom-0 z-10 border-t-[3px] border-neo-ink bg-neo-bg px-4 pb-20 pt-4">
        <InputBar
          onSend={handleSend}
          onUpload={handleUpload}
          disabled={isStreaming || isGenerating}
          isUploading={isUploading}
          placeholder={`围绕「${selectedSubject?.name ?? "通用笔记本"}」开始提问...`}
        />
      </div>

      <BottomNav />

      <HistoryDrawer
        isOpen={showHistory}
        onClose={() => setShowHistory(false)}
        sessions={sessions}
        subjects={subjects}
        onSelectSession={(session) => {
          activeStreamRef.current?.abort();
          activeStreamRef.current = null;
          setIsStreaming(false);
          setSelectedSubjectId(session.subjectId);
          persistStoredSubjectId(session.subjectId);
          setCurrentSessionId(session.id);
          setMessages(session.messages);
          setShowHistory(false);
        }}
        onDeleteSession={(id) => {
          void deleteSessionRemote(DEFAULT_USER_ID, id)
            .then(() => refreshSessions())
            .catch((error) => {
              console.error("删除聊天记录失败:", error);
            });
          if (currentSessionId === id) {
            handleNewSession();
          }
        }}
        onNewSession={handleNewSession}
      />

      {showStyleOnboarding && (
        <AgentStyleOnboardingModal
          profile={userProfile}
          isSaving={isSavingStyle}
          onClose={() => setShowStyleOnboarding(false)}
          onSave={handleSaveStyle}
          onSkip={handleSkipStyleSetup}
        />
      )}
    </div>
  );
}
