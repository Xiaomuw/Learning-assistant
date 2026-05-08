"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Filter,
  Info,
  KeyRound,
  LogOut,
  MessageSquareQuote,
  MessageSquareText,
  NotebookPen,
  PencilLine,
  Settings,
  ShieldCheck,
  Trash2,
  UserCircle,
  X,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import BottomNav from "@/components/BottomNav";
import ModelSelectorCard from "@/components/ModelSelectorCard";
import AgentStyleEditor from "@/components/AgentStyleEditor";
import SessionSummaryCard, {
  hasSessionSummary,
} from "@/components/SessionSummaryCard";
import {
  changePasswordWithCurrentSession,
  deleteSession,
  fetchNotebookKnowledgeStatus,
  fetchModelConfig,
  fetchModelHealth,
  fetchNotebooks,
  fetchPracticeRecommendations,
  fetchSessions,
  fetchUserProfile,
  updateModelConfig,
  updateUserProfile,
  type ChatSession,
  type ModelConfig,
  type Notebook,
  type NotebookKnowledgeStatus,
  type QuizItem,
  type UserProfile,
} from "@/lib/api";
import {
  loadStoredModelConfig,
  persistQuiz,
  persistStoredModelConfig,
} from "@/lib/learning-store";

type NoticeTone = "success" | "error" | "info";

export default function ProfilePage() {
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();
  const userId = user?.id ?? "";

  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [isLoadingModelConfig, setIsLoadingModelConfig] = useState(false);
  const [modelConfigError, setModelConfigError] = useState<string | null>(null);
  const [isSwitchingModel, setIsSwitchingModel] = useState(false);
  const [showModelSettings, setShowModelSettings] = useState(false);
  const [modelHealthStatus, setModelHealthStatus] = useState<
    "idle" | "checking" | "ok" | "error"
  >("idle");
  const [modelHealthMessage, setModelHealthMessage] = useState<string | null>(null);

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [showAgentStyleSettings, setShowAgentStyleSettings] = useState(false);
  const [showSecuritySettings, setShowSecuritySettings] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [knowledgeStatusByNotebookId, setKnowledgeStatusByNotebookId] = useState<
    Record<string, NotebookKnowledgeStatus>
  >({});

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [showHistoryManager, setShowHistoryManager] = useState(false);
  const [historyFilterNotebookId, setHistoryFilterNotebookId] = useState("all");
  const [historyQuery, setHistoryQuery] = useState("");
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null);
  const [isExitConfirmOpen, setIsExitConfirmOpen] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [recommendedPractice, setRecommendedPractice] = useState<QuizItem[]>([]);
  const [showRecommendedPractice, setShowRecommendedPractice] = useState(false);

  const [showEditProfile, setShowEditProfile] = useState(false);
  const [draftDisplayName, setDraftDisplayName] = useState("");
  const [isSavingDisplayName, setIsSavingDisplayName] = useState(false);

  const [notice, setNotice] = useState<{
    tone: NoticeTone;
    text: string;
  } | null>(null);
  const [showAuthRecoveryHint, setShowAuthRecoveryHint] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      setShowAuthRecoveryHint(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setShowAuthRecoveryHint(true);
    }, 6000);

    return () => {
      window.clearTimeout(timer);
    };
  }, [isLoading]);

  useEffect(() => {
    if (isLoading || !userId) {
      return;
    }

    let isMounted = true;

    const cachedModelConfig = loadStoredModelConfig();
    if (cachedModelConfig) {
      setModelConfig(cachedModelConfig);
    }

    void fetchNotebooks()
      .then((remoteNotebooks) => {
        if (!isMounted) {
          return;
        }

        setNotebooks(remoteNotebooks);
        setKnowledgeStatusByNotebookId({});
        void Promise.allSettled(
          remoteNotebooks.map((notebook) => fetchNotebookKnowledgeStatus(notebook.id))
        ).then((results) => {
          if (!isMounted) {
            return;
          }
          const nextStatus: Record<string, NotebookKnowledgeStatus> = {};
          results.forEach((result) => {
            if (result.status === "fulfilled") {
              nextStatus[result.value.notebookId] = result.value;
            }
          });
          setKnowledgeStatusByNotebookId(nextStatus);
        });
      })
      .catch((error) => {
        console.error(error);
        if (isMounted) {
          setNotebooks([]);
          setKnowledgeStatusByNotebookId({});
        }
      });

    void fetchUserProfile(userId)
      .then((userProfile) => {
        if (isMounted) {
          setProfile(userProfile);
        }
      })
      .catch((error) => {
        console.error(error);
      });

    void fetchSessions(userId)
      .then((remoteSessions) => {
        if (isMounted) {
          setSessions(remoteSessions);
        }
      })
      .catch((error) => {
        console.error(error);
        if (isMounted) {
          setSessions([]);
        }
      });

    void fetchPracticeRecommendations(userId)
      .then((practiceRecommendations) => {
        if (isMounted) {
          setRecommendedPractice(practiceRecommendations.items);
        }
      })
      .catch((error) => {
        console.error(error);
        if (isMounted) {
          setRecommendedPractice([]);
        }
      });

    void loadModelConfig();

    return () => {
      isMounted = false;
    };
  }, [isLoading, userId]);

  const displayName = profile?.display_name?.trim() || "学习者_7492";
  const notebookCount = notebooks.length;
  const getNotebookDocCount = (notebook: Notebook) =>
    knowledgeStatusByNotebookId[notebook.id]?.doc_count ?? notebook.doc_count ?? 0;
  const totalSources = notebooks.reduce(
    (total, notebook) => total + getNotebookDocCount(notebook),
    0
  );
  const filteredSessions = sessions.filter((session) => {
    const matchesNotebook =
      historyFilterNotebookId === "all" || session.notebookId === historyFilterNotebookId;

    if (!matchesNotebook) {
      return false;
    }

    const keyword = historyQuery.trim().toLowerCase();
    if (!keyword) {
      return true;
    }

    const notebook = notebooks.find((item) => item.id === session.notebookId);
    const haystack = [
      session.title,
      notebook?.name ?? "",
      session.messages.at(-1)?.content ?? "",
      session.sessionMemory?.summaryText ?? "",
      session.sessionMemory?.activeTopic ?? "",
      session.sessionMemory?.currentGoal ?? "",
      ...(session.sessionMemory?.openLoops ?? []),
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(keyword);
  });
  const highlightedSession =
    filteredSessions.find((session) => hasSessionSummary(session.sessionMemory)) ??
    sessions.find((session) => hasSessionSummary(session.sessionMemory));
  const highlightedSessionNotebook = highlightedSession
    ? notebooks.find((item) => item.id === highlightedSession.notebookId) ?? null
    : null;

  function showFeedback(tone: NoticeTone, text: string) {
    setNotice({ tone, text });
  }

  async function loadModelConfig() {
    setIsLoadingModelConfig(true);
    setModelConfigError(null);

    try {
      const config = await fetchModelConfig();
      setModelConfig(config);
      persistStoredModelConfig(config);
    } catch (error) {
      console.error("加载模型配置失败", error);
      setModelConfigError(
        error instanceof Error ? error.message : "模型服务暂时不可用"
      );
    } finally {
      setIsLoadingModelConfig(false);
    }
  }

  async function refreshSessions() {
    if (!user) {
      return;
    }
    try {
      const data = await fetchSessions(user.id);
      setSessions(data);
    } catch (error) {
      console.error("Failed to refresh sessions:", error);
      showFeedback("error", "刷新聊天历史失败，请稍后重试。");
    }
  }

  async function handleModelChange(modelId: string) {
    if (!modelConfig || modelId === modelConfig.current_model) {
      return;
    }

    setIsSwitchingModel(true);
    try {
      const nextConfig = await updateModelConfig(modelId);
      setModelConfig(nextConfig);
      persistStoredModelConfig(nextConfig);
      setModelConfigError(null);
      showFeedback("success", `已切换到模型：${nextConfig.current_model}`);
    } catch (error) {
      console.error("模型切换失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "模型切换失败，请稍后重试。"
      );
    } finally {
      setIsSwitchingModel(false);
    }
  }

  async function handleModelHealthCheck() {
    setModelHealthStatus("checking");
    setModelHealthMessage(null);

    try {
      const result = await fetchModelHealth();
      const modelLabel =
        modelConfig?.available_models.find((item) => item.id === result.chat_model)?.label ??
        result.chat_model;
      if (result.chat_model_ok) {
        setModelHealthStatus("ok");
        setModelHealthMessage(`${modelLabel} 可用，聊天请求会优先使用当前主模型。`);
        showFeedback("success", `${modelLabel} 连接测试通过。`);
        return;
      }

      setModelHealthStatus("error");
      setModelHealthMessage(
        result.chat_model_error
          ? `${modelLabel} 当前不可用：${result.chat_model_error}`
          : `${modelLabel} 当前不可用，请检查本地模型密钥或账号权限。`
      );
    } catch (error) {
      console.error("模型连接测试失败", error);
      setModelHealthStatus("error");
      setModelHealthMessage(
        error instanceof Error ? error.message : "模型连接测试失败。"
      );
    }
  }

  async function handleSaveProfile(payload: {
    agent_style_name: string;
    agent_style_prompt: string;
    onboarding_completed: boolean;
  }) {
    if (!user) {
      return;
    }
    setIsSavingProfile(true);
    try {
      const nextProfile = await updateUserProfile(user.id, payload);
      setProfile(nextProfile);
      showFeedback(
        "success",
        nextProfile.agent_style_name
          ? `已保存风格「${nextProfile.agent_style_name}」`
          : "已恢复为默认表达风格。"
      );
    } catch (error) {
      console.error("保存 Agent 风格失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "保存风格失败，请稍后重试。"
      );
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleSaveDisplayName() {
    if (!user) {
      return;
    }

    const nextName = draftDisplayName.trim();
    if (!nextName) {
      showFeedback("error", "昵称不能为空。");
      return;
    }

    setIsSavingDisplayName(true);
    try {
      const nextProfile = await updateUserProfile(user.id, {
        display_name: nextName,
      });
      setProfile(nextProfile);
      setShowEditProfile(false);
      showFeedback("success", `已更新昵称为「${nextProfile.display_name}」`);
    } catch (error) {
      console.error("保存昵称失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "保存昵称失败，请稍后重试。"
      );
    } finally {
      setIsSavingDisplayName(false);
    }
  }

  function handleDeleteSession(sessionId: string) {
    setPendingDeleteSessionId(sessionId);
  }

  async function handleConfirmDeleteSession() {
    if (!user || !pendingDeleteSessionId) {
      return;
    }

    setDeletingSessionId(pendingDeleteSessionId);
    try {
      await deleteSession(user.id, pendingDeleteSessionId);
      await refreshSessions();
      setPendingDeleteSessionId(null);
      showFeedback("success", "聊天记录已删除。");
    } catch (error) {
      console.error("删除聊天记录失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "删除聊天记录失败，请稍后重试。"
      );
    } finally {
      setDeletingSessionId(null);
    }
  }

  function handleExit() {
    setIsExitConfirmOpen(true);
  }

  async function handleConfirmExit() {
    setIsExitConfirmOpen(false);
    await logout();
    router.push("/login");
  }

  async function handleChangePassword() {
    if (!currentPassword || !newPassword || !confirmNewPassword) {
      showFeedback("error", "请把当前密码、新密码和确认密码都填完整。");
      return;
    }

    if (newPassword.length < 8) {
      showFeedback("error", "新密码至少需要 8 位。");
      return;
    }

    if (newPassword !== confirmNewPassword) {
      showFeedback("error", "两次输入的新密码不一致。");
      return;
    }

    setIsChangingPassword(true);
    try {
      await changePasswordWithCurrentSession(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmNewPassword("");
      showFeedback("success", "密码已更新，当前设备的登录态也已经同步刷新。");
    } catch (error) {
      console.error("修改密码失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "修改密码失败，请稍后重试。"
      );
    } finally {
      setIsChangingPassword(false);
    }
  }

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-4">
        <div className="neo-card-secondary w-full p-5 text-center">
          <p className="neo-label">Profile</p>
          <p className="mt-3 text-lg font-black">
            {isLoading ? "正在恢复你的个人中心…" : "登录状态已失效"}
          </p>
          <p className="mt-3 text-sm font-bold leading-relaxed text-neo-ink/70">
            {isLoading
              ? "如果你刚刚更新过本地服务，当前标签页可能还停留在旧状态。"
              : "重新登录后就可以继续查看模型设置、资料库和聊天历史。"}
          </p>
          {(showAuthRecoveryHint || !isLoading) && (
            <div className="mt-5 space-y-3">
              <button
                type="button"
                onClick={() => router.refresh()}
                className="neo-button w-full justify-center"
              >
                重新加载
              </button>
              <Link
                href="/login?next=%2Fprofile"
                className="neo-button-secondary flex w-full items-center justify-center"
              >
                重新登录
              </Link>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0 flex-col neo-grid bg-neo-bg">
      <header className="sticky top-0 z-10 flex items-center justify-center border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4 shadow-neo-sm">
        <h1 className="text-xl font-black uppercase tracking-widest text-neo-ink">
          我的
        </h1>
      </header>

      <main className="flex-1 space-y-6 overflow-y-auto p-4 pb-24">
        {notice && (
          <div
            className={`neo-card flex items-start justify-between gap-3 p-4 ${
              notice.tone === "success"
                ? "bg-neo-secondary"
                : notice.tone === "error"
                  ? "bg-neo-accent"
                  : "bg-neo-muted"
            }`}
          >
            <p className="text-sm font-bold leading-relaxed">{notice.text}</p>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="flex h-8 w-8 items-center justify-center border-[3px] border-neo-ink bg-white shadow-neo-sm"
              aria-label="关闭提示"
            >
              <X size={16} strokeWidth={2.8} />
            </button>
          </div>
        )}



        <div className="neo-card flex items-center gap-4 p-5">
          <div className="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-[1.5rem] border-[3px] border-neo-ink bg-neo-accent shadow-neo-sm">
            <UserCircle size={40} className="text-neo-ink" strokeWidth={2.5} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-black text-neo-ink">
              {displayName}
            </h2>
            <p className="mt-1 truncate text-sm font-bold tracking-widest text-neo-ink/60">
              ID: {user.id}
            </p>
            <p className="mt-1 truncate text-xs font-bold text-neo-ink/60">
              {user.email}
            </p>
            <p className="mt-2 text-xs font-bold text-neo-ink/70">
              {profile?.agent_style_name
                ? `当前风格：${profile.agent_style_name}`
                : "尚未设置专属 Agent 风格"}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setDraftDisplayName(displayName);
              setShowEditProfile(true);
            }}
            className="neo-button px-3 py-2 text-xs"
          >
            <PencilLine size={14} strokeWidth={2.8} />
            编辑
          </button>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="neo-card-muted neo-card-lift flex flex-col items-center justify-center gap-1 p-4">
            <span className="text-3xl font-black">{notebookCount}</span>
            <span className="neo-label">默认知识库</span>
          </div>
          <div className="neo-card-secondary neo-card-lift flex flex-col items-center justify-center gap-1 p-4">
            <span className="text-3xl font-black">{totalSources}</span>
            <span className="neo-label">总来源数</span>
          </div>
        </div>

        <section className="neo-card bg-white p-4">
          <button
            type="button"
            onClick={() => setShowRecommendedPractice((current) => !current)}
            className="group flex w-full items-start justify-between gap-4 text-left"
          >
            <div>
              <p className="neo-label">Recommended Practice</p>
              <h2 className="mt-2 text-2xl font-black">基于薄弱点的推荐题</h2>
              <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
                优先推送历年真题，不够时会自动补 AI 单选题，适合直接拿来热身。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="neo-badge bg-neo-secondary">
                {recommendedPractice.length} 题
              </span>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className={`transition-transform duration-200 ${
                  showRecommendedPractice ? "rotate-90" : "group-hover:translate-x-1"
                }`}
              />
            </div>
          </button>

          {showRecommendedPractice ? (
            <>
              {recommendedPractice.length === 0 ? (
                <div className="neo-card-secondary mt-4 p-4">
                  <p className="text-sm font-bold leading-relaxed">
                    目前还没有可推荐的题目。你可以先去问答页生成题包，或者导入历年真题题库。
                  </p>
                </div>
              ) : (
                <>
                  <div className="mt-4 space-y-3">
                    {recommendedPractice.slice(0, 2).map((item) => (
                      <div
                        key={item.question_id}
                        className="border-[3px] border-neo-ink bg-neo-bg p-4 shadow-neo-sm"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="neo-badge bg-neo-accent">
                            {item.difficulty}
                          </span>
                          <span className="neo-badge bg-white">
                            {item.knowledge_point}
                          </span>
                          <span className="neo-badge bg-neo-secondary">
                            {item.source_type === "question_bank"
                              ? item.source_year
                                ? `${item.source_name} · ${item.source_year}`
                                : item.source_name || "题库真题"
                              : "AI 补题"}
                          </span>
                        </div>
                        <p className="mt-3 text-sm font-black leading-relaxed">
                          {item.question}
                        </p>
                        <div className="mt-3 grid grid-cols-2 gap-2">
                          {item.options?.slice(0, 4).map((option) => (
                            <div
                              key={`${item.question_id}-${option.key}`}
                              className="border-[3px] border-neo-ink bg-white p-3"
                            >
                              <div className="flex items-start gap-2">
                                <span className="neo-badge bg-neo-bg">
                                  {option.key}
                                </span>
                                <p className="text-xs font-bold leading-relaxed">
                                  {option.text}
                                </p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      persistQuiz(recommendedPractice);
                      router.push("/practice");
                    }}
                    className="neo-button mt-4 w-full justify-center"
                  >
                    <CheckCircle2 size={16} strokeWidth={2.8} />
                    开始做这组推荐题
                  </button>
                </>
              )}
            </>
          ) : null}
        </section>

        <div className="neo-card flex flex-col divide-y-4 divide-neo-ink">
          <div className="group my-[-4px] flex flex-col">
            <button
              type="button"
              onClick={() =>
                showFeedback("info", "我的笔记本管理入口暂未开放；当前请在问答页顶部选择知识库。")
              }
              className="flex items-center justify-between bg-neo-secondary p-4 text-left transition-colors hover:bg-neo-accent"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-[2px_2px_0px_0px_#1e293b]">
                  <NotebookPen size={20} strokeWidth={2.5} />
                </div>
                <span className="font-bold text-base">我的笔记本</span>
              </div>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className="transition-transform duration-200 group-hover:translate-x-1"
              />
            </button>
          </div>

          <div className="group my-[-4px] flex flex-col border-y-4 border-dashed border-neo-ink">
            <button
              onClick={() => setShowHistoryManager(!showHistoryManager)}
              className="flex items-center justify-between bg-neo-bg p-4 text-left transition-colors hover:bg-neo-muted"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-[2px_2px_0px_0px_#1e293b]">
                  <Clock3 size={20} strokeWidth={2.5} />
                </div>
                <div>
                  <span className="block font-bold text-base">聊天历史管理</span>
                  <span className="mt-1 block text-xs font-bold text-neo-ink/60">
                    共 {sessions.length} 条记录
                  </span>
                </div>
              </div>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className={`transition-transform duration-200 ${
                  showHistoryManager ? "rotate-90" : "group-hover:translate-x-1"
                }`}
              />
            </button>
            {showHistoryManager && (
              <div className="animate-in slide-in-from-top-2 bg-neo-bg p-4 pt-0 duration-200">
                <div className="space-y-3">
                  {highlightedSession && (
                    <SessionSummaryCard
                      session={highlightedSession}
                      notebook={highlightedSessionNotebook}
                      title="继续学习摘要"
                      continueLabel="回到会话"
                      onContinue={() =>
                        router.push(
                          `/chat?notebook=${highlightedSession.notebookId}&session=${highlightedSession.id}`
                        )
                      }
                    />
                  )}

                  <label className="block">
                    <span className="neo-label mb-2 block">搜索聊天记录</span>
                    <input
                      value={historyQuery}
                      onChange={(event) => setHistoryQuery(event.target.value)}
                      className="neo-input w-full"
                      placeholder="按标题、笔记本或最后一条内容搜索"
                    />
                  </label>

                  <label className="block">
                    <span className="neo-label mb-2 block">按笔记本筛选</span>
                    <div className="relative">
                      <select
                        value={historyFilterNotebookId}
                        onChange={(event) => setHistoryFilterNotebookId(event.target.value)}
                        className="neo-input w-full appearance-none pr-12"
                      >
                        <option value="all">全部笔记本</option>
                        {notebooks.map((notebook) => (
                          <option key={notebook.id} value={notebook.id}>
                            {notebook.name}
                          </option>
                        ))}
                      </select>
                      <Filter
                        size={16}
                        strokeWidth={2.8}
                        className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2"
                      />
                    </div>
                  </label>

                  {sessions.length === 0 ? (
                    <div className="neo-card p-4 text-center">
                      <MessageSquareText
                        className="mx-auto"
                        size={24}
                        strokeWidth={2.8}
                      />
                      <p className="mt-3 text-sm font-bold">
                        你还没有聊天记录，去问答页开始第一轮学习吧。
                      </p>
                    </div>
                  ) : filteredSessions.length === 0 ? (
                    <div className="neo-card p-4 text-center">
                      <p className="text-sm font-bold">
                        当前筛选条件下没有聊天记录。
                      </p>
                    </div>
                  ) : (
                    filteredSessions.slice(0, 8).map((session) => {
                      const notebook = notebooks.find((item) => item.id === session.notebookId);
                      const date = new Date(session.updatedAt);
                      const dateString = `${date.getMonth() + 1}/${date.getDate()} ${date
                        .getHours()
                        .toString()
                        .padStart(2, "0")}:${date
                        .getMinutes()
                        .toString()
                        .padStart(2, "0")}`;

                      return (
                        <div key={session.id} className="neo-card p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-lg">{notebook?.icon ?? "📚"}</span>
                                <p className="truncate text-sm font-black">
                                  {session.title}
                                </p>
                              </div>
                              <p className="mt-2 text-xs font-bold text-neo-ink/60">
                                {notebook?.name ?? "未知笔记本"} · {dateString}
                              </p>
                              {hasSessionSummary(session.sessionMemory) && (
                                <div className="mt-2 space-y-1">
                                  {session.sessionMemory?.activeTopic && (
                                    <p className="text-xs font-black text-neo-ink">
                                      主题：{session.sessionMemory.activeTopic}
                                    </p>
                                  )}
                                  {session.sessionMemory?.currentGoal && (
                                    <p className="text-xs font-bold text-neo-ink/70">
                                      目标：{session.sessionMemory.currentGoal}
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                            <span className="neo-badge bg-white">
                              {session.messages.length} 条
                            </span>
                          </div>

                          <div className="mt-3 grid grid-cols-2 gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                router.push(
                                  `/chat?notebook=${session.notebookId}&session=${session.id}`
                                )
                              }
                              className="neo-button w-full justify-center px-3 py-2 text-xs"
                            >
                              继续学习
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeleteSession(session.id)}
                              disabled={deletingSessionId === session.id}
                              className="neo-button-ghost w-full justify-center px-3 py-2 text-xs hover:bg-neo-accent"
                            >
                              <Trash2 size={14} strokeWidth={2.8} />
                              {deletingSessionId === session.id ? "删除中" : "删除记录"}
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}

                  {filteredSessions.length > 8 && (
                    <p className="text-center text-xs font-bold text-neo-ink/60">
                      当前只展示最近 8 条记录，其余历史可在问答页继续查看。
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="group my-[-4px] flex flex-col border-y-4 border-dashed border-neo-ink">
            <button
              onClick={() => setShowAgentStyleSettings(!showAgentStyleSettings)}
              className="flex items-center justify-between bg-white p-4 text-left transition-colors hover:bg-neo-muted"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-[2px_2px_0px_0px_#1e293b]">
                  <MessageSquareQuote size={20} strokeWidth={2.5} />
                </div>
                <div>
                  <span className="block font-bold text-base">Agent 风格设置</span>
                  <span className="mt-1 block text-xs font-bold text-neo-ink/60">
                    {profile?.agent_style_name || "尚未设置"}
                  </span>
                </div>
              </div>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className={`transition-transform duration-200 ${
                  showAgentStyleSettings
                    ? "rotate-90"
                    : "group-hover:translate-x-1"
                }`}
              />
            </button>
            {showAgentStyleSettings && (
              <div className="animate-in slide-in-from-top-2 bg-white p-4 pt-0 duration-200">
                <AgentStyleEditor
                  profile={profile}
                  isSaving={isSavingProfile}
                  title="设置你的专属说话方式"
                  description="这是用户级设置，不属于某个笔记本。设置后，你在所有笔记本里的回答口吻都会按这里来。"
                  submitLabel="保存风格"
                  onSave={handleSaveProfile}
                />
              </div>
            )}
          </div>

          <div className="group my-[-4px] flex flex-col border-y-4 border-dashed border-neo-ink">
            <button
              onClick={() => setShowSecuritySettings(!showSecuritySettings)}
              className="flex items-center justify-between bg-white p-4 text-left transition-colors hover:bg-neo-muted"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-[2px_2px_0px_0px_#1e293b]">
                  <ShieldCheck size={20} strokeWidth={2.5} />
                </div>
                <div>
                  <span className="block font-bold text-base">账号安全</span>
                  <span className="mt-1 block text-xs font-bold text-neo-ink/60">
                    修改密码与基础安全设置
                  </span>
                </div>
              </div>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className={`transition-transform duration-200 ${
                  showSecuritySettings
                    ? "rotate-90"
                    : "group-hover:translate-x-1"
                }`}
              />
            </button>
            {showSecuritySettings && (
              <div className="animate-in slide-in-from-top-2 bg-white p-4 pt-0 duration-200">
                <div className="neo-card-secondary p-4">
                  <p className="neo-label">Password</p>
                  <h3 className="mt-2 text-xl font-black">修改登录密码</h3>
                  <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
                    修改后会轮换当前登录会话，旧的 refresh token 会被作废。
                  </p>

                  <div className="mt-4 space-y-3">
                    <label className="block">
                      <span className="neo-label mb-2 block">当前密码</span>
                      <div className="flex items-center gap-3 border-[3px] border-neo-ink bg-white px-4 py-3 shadow-neo-sm">
                        <KeyRound size={16} strokeWidth={2.8} />
                        <input
                          type="password"
                          value={currentPassword}
                          onChange={(event) => setCurrentPassword(event.target.value)}
                          placeholder="输入当前密码"
                          className="w-full bg-transparent text-sm font-bold outline-none"
                          autoComplete="current-password"
                        />
                      </div>
                    </label>

                    <label className="block">
                      <span className="neo-label mb-2 block">新密码</span>
                      <div className="flex items-center gap-3 border-[3px] border-neo-ink bg-white px-4 py-3 shadow-neo-sm">
                        <KeyRound size={16} strokeWidth={2.8} />
                        <input
                          type="password"
                          value={newPassword}
                          onChange={(event) => setNewPassword(event.target.value)}
                          placeholder="至少 8 位"
                          className="w-full bg-transparent text-sm font-bold outline-none"
                          autoComplete="new-password"
                        />
                      </div>
                    </label>

                    <label className="block">
                      <span className="neo-label mb-2 block">确认新密码</span>
                      <div className="flex items-center gap-3 border-[3px] border-neo-ink bg-white px-4 py-3 shadow-neo-sm">
                        <KeyRound size={16} strokeWidth={2.8} />
                        <input
                          type="password"
                          value={confirmNewPassword}
                          onChange={(event) => setConfirmNewPassword(event.target.value)}
                          placeholder="再输入一次新密码"
                          className="w-full bg-transparent text-sm font-bold outline-none"
                          autoComplete="new-password"
                        />
                      </div>
                    </label>
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      void handleChangePassword();
                    }}
                    disabled={isChangingPassword}
                    className="neo-button mt-4 w-full justify-center"
                  >
                    <ShieldCheck size={16} strokeWidth={2.8} />
                    {isChangingPassword ? "更新中…" : "更新密码"}
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="group my-[-4px] flex flex-col border-y-4 border-dashed border-neo-ink">
            <button
              onClick={() => setShowModelSettings(!showModelSettings)}
              className="flex items-center justify-between bg-neo-accent p-4 text-left transition-colors hover:bg-[#eadeff]/80"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-[2px_2px_0px_0px_#1e293b]">
                  <Settings size={20} strokeWidth={2.5} />
                </div>
                <span className="font-bold text-base">大模型设置</span>
              </div>
              <ChevronRight
                size={24}
                strokeWidth={2.5}
                className={`transition-transform duration-200 ${
                  showModelSettings ? "rotate-90" : "group-hover:translate-x-1"
                }`}
              />
            </button>
            {showModelSettings && (
              <div className="animate-in slide-in-from-top-2 bg-neo-accent p-4 pt-0 duration-200">
                <ModelSelectorCard
                  config={modelConfig}
                  isLoading={isLoadingModelConfig}
                  error={modelConfigError}
                  isUpdating={isSwitchingModel}
                  healthStatus={modelHealthStatus}
                  healthMessage={modelHealthMessage}
                  onChange={handleModelChange}
                  onRetry={() => {
                    void loadModelConfig();
                  }}
                  onTestHealth={() => {
                    void handleModelHealthCheck();
                  }}
                />
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => router.push("/help")}
            className="group flex items-center justify-between p-4 text-left transition-colors hover:bg-neo-muted"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white transition-shadow group-hover:shadow-[2px_2px_0px_0px_#1e293b]">
                <Info size={20} strokeWidth={2.5} />
              </div>
              <span className="font-bold text-base">系统介绍</span>
            </div>
            <ChevronRight
              size={24}
              strokeWidth={2.5}
              className="transition-transform group-hover:translate-x-1"
            />
          </button>
        </div>

        <div className="pt-2">
          <button
            type="button"
            onClick={handleExit}
            className="neo-button-ghost w-full justify-center bg-white text-neo-ink hover:bg-neo-accent"
          >
            <LogOut size={16} strokeWidth={2.8} />
            退出登录
          </button>
        </div>
      </main>

      <BottomNav />

      {pendingDeleteSessionId && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-session-confirm-title"
            className="neo-card w-full max-w-md p-5"
          >
            <p className="neo-label">Danger Zone</p>
            <h2 id="delete-session-confirm-title" className="mt-2 text-xl font-black">
              删除这条聊天记录？
            </h2>
            <p className="mt-3 text-sm font-bold leading-relaxed text-neo-ink/70">
              删除后无法恢复。这个操作只会影响当前选择的聊天记录。
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setPendingDeleteSessionId(null)}
                disabled={Boolean(deletingSessionId)}
                className="neo-button-ghost w-full justify-center"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleConfirmDeleteSession();
                }}
                disabled={Boolean(deletingSessionId)}
                className="neo-button w-full justify-center bg-neo-accent"
              >
                {deletingSessionId === pendingDeleteSessionId ? "删除中" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}

      {isExitConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="logout-confirm-title"
            className="neo-card w-full max-w-md p-5"
          >
            <p className="neo-label">Sign Out</p>
            <h2 id="logout-confirm-title" className="mt-2 text-xl font-black">
              退出当前账号？
            </h2>
            <p className="mt-3 text-sm font-bold leading-relaxed text-neo-ink/70">
              退出后会返回登录页，之后访问问答、刷题、中心和我的页面都需要重新登录。
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setIsExitConfirmOpen(false)}
                className="neo-button-ghost w-full justify-center"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleConfirmExit();
                }}
                className="neo-button w-full justify-center bg-neo-accent"
              >
                确认退出
              </button>
            </div>
          </div>
        </div>
      )}

      {showEditProfile && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center">
          <div className="neo-card w-full max-w-md p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="neo-label">Profile</p>
                <h2 className="mt-2 text-xl font-black">编辑昵称</h2>
              </div>
              <button
                type="button"
                onClick={() => setShowEditProfile(false)}
                className="flex h-10 w-10 items-center justify-center border-[3px] border-neo-ink bg-white shadow-neo-sm"
                aria-label="关闭昵称编辑"
              >
                <X size={16} strokeWidth={2.8} />
              </button>
            </div>

            <label className="mt-5 block">
              <span className="neo-label mb-2 block">显示昵称</span>
              <input
                value={draftDisplayName}
                onChange={(event) => setDraftDisplayName(event.target.value)}
                maxLength={120}
                placeholder="例如：数据库冲刺中的小木"
                className="neo-input w-full"
              />
            </label>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setShowEditProfile(false)}
                className="neo-button-ghost w-full justify-center"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveDisplayName}
                disabled={isSavingDisplayName}
                className="neo-button w-full justify-center"
              >
                {isSavingDisplayName ? "保存中" : "保存昵称"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
