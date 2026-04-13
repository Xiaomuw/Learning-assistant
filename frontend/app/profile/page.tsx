"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  ChevronRight,
  Clock3,
  Filter,
  Info,
  LogOut,
  MessageSquareQuote,
  MessageSquareText,
  NotebookPen,
  PencilLine,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  UserCircle,
  X,
} from "lucide-react";
import BottomNav from "@/components/BottomNav";
import ModelSelectorCard from "@/components/ModelSelectorCard";
import CreateAgentModal from "@/components/CreateAgentModal";
import AgentStyleEditor from "@/components/AgentStyleEditor";
import EditNotebookModal from "@/components/EditNotebookModal";
import {
  DEFAULT_USER_ID,
  deleteSubject,
  deleteSession,
  fetchModelConfig,
  fetchSessions,
  fetchSubjects,
  fetchUserProfile,
  generateKnowledgeBase,
  updateModelConfig,
  updateUserProfile,
  uploadPDFWithSubject,
  type ChatSession,
  type ModelConfig,
  type Subject,
  type UserProfile,
} from "@/lib/api";
import {
  clearLearningStore,
  loadStoredModelConfig,
  persistStoredModelConfig,
} from "@/lib/learning-store";

const BUILTIN_NOTEBOOK_IDS = new Set([
  "operating-system",
  "database",
  "data-structure",
  "probability",
  "linear-algebra",
  "computer-network",
  "general",
  "math",
]);

type NoticeTone = "success" | "error" | "info";

export default function ProfilePage() {
  const router = useRouter();
  const uploadInputRef = useRef<HTMLInputElement>(null);

  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [isLoadingModelConfig, setIsLoadingModelConfig] = useState(false);
  const [modelConfigError, setModelConfigError] = useState<string | null>(null);
  const [isSwitchingModel, setIsSwitchingModel] = useState(false);
  const [showModelSettings, setShowModelSettings] = useState(false);

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [showAgentStyleSettings, setShowAgentStyleSettings] = useState(false);

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showKnowledgeBase, setShowKnowledgeBase] = useState(true);
  const [notebookQuery, setNotebookQuery] = useState("");
  const [notebookSort, setNotebookSort] = useState("default");
  const [notebookSourceFilter, setNotebookSourceFilter] = useState("all");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingSubject, setEditingSubject] = useState<Subject | null>(null);
  const [generatingSubjectId, setGeneratingSubjectId] = useState<string | null>(null);
  const [deletingSubjectId, setDeletingSubjectId] = useState<string | null>(null);
  const [uploadingSubjectId, setUploadingSubjectId] = useState<string | null>(null);
  const [pendingUploadSubjectId, setPendingUploadSubjectId] = useState<string | null>(
    null
  );

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [showHistoryManager, setShowHistoryManager] = useState(false);
  const [historyFilterSubjectId, setHistoryFilterSubjectId] = useState("all");
  const [historyQuery, setHistoryQuery] = useState("");
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const [showEditProfile, setShowEditProfile] = useState(false);
  const [draftDisplayName, setDraftDisplayName] = useState("");
  const [isSavingDisplayName, setIsSavingDisplayName] = useState(false);

  const [notice, setNotice] = useState<{
    tone: NoticeTone;
    text: string;
  } | null>(null);

  useEffect(() => {
    let isMounted = true;

    const cachedModelConfig = loadStoredModelConfig();
    if (cachedModelConfig) {
      setModelConfig(cachedModelConfig);
    }

    Promise.all([
      fetchSubjects().catch((error) => {
        console.error(error);
        return [];
      }),
      fetchUserProfile(DEFAULT_USER_ID).catch((error) => {
        console.error(error);
        return null;
      }),
      fetchSessions(DEFAULT_USER_ID).catch((error) => {
        console.error(error);
        return [];
      }),
    ]).then(([notebooks, userProfile, remoteSessions]) => {
      if (!isMounted) {
        return;
      }

      if (notebooks) {
        setSubjects(notebooks);
      }

      if (userProfile) {
        setProfile(userProfile);
      }

      if (remoteSessions) {
        setSessions(remoteSessions);
      }
    });

    void loadModelConfig();

    return () => {
      isMounted = false;
    };
  }, []);

  const displayName = profile?.display_name?.trim() || "学习者_7492";
  const notebookCount = subjects.filter((subject) => subject.id !== "general").length;
  const totalSources = subjects.reduce(
    (total, subject) => total + (subject.doc_count ?? 0),
    0
  );
  const filteredSubjects = subjects
    .filter((subject) => {
      const keyword = notebookQuery.trim().toLowerCase();
      const matchesSourceFilter =
        notebookSourceFilter === "all"
          ? true
          : notebookSourceFilter === "with-sources"
            ? (subject.doc_count ?? 0) > 0
            : (subject.doc_count ?? 0) === 0;

      if (!matchesSourceFilter) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      return (
        subject.name.toLowerCase().includes(keyword) ||
        subject.description.toLowerCase().includes(keyword) ||
        subject.id.toLowerCase().includes(keyword)
      );
    })
    .sort((left, right) => {
      if (notebookSort === "sources-desc") {
        return (right.doc_count ?? 0) - (left.doc_count ?? 0);
      }

      if (notebookSort === "name-asc") {
        return left.name.localeCompare(right.name, "zh-Hans-CN");
      }

      if (notebookSort === "custom-first") {
        return Number(BUILTIN_NOTEBOOK_IDS.has(left.id)) - Number(BUILTIN_NOTEBOOK_IDS.has(right.id));
      }

      return 0;
    });
  const filteredSessions = sessions.filter((session) => {
    const matchesSubject =
      historyFilterSubjectId === "all" || session.subjectId === historyFilterSubjectId;

    if (!matchesSubject) {
      return false;
    }

    const keyword = historyQuery.trim().toLowerCase();
    if (!keyword) {
      return true;
    }

    const subject = subjects.find((item) => item.id === session.subjectId);
    const haystack = [
      session.title,
      subject?.name ?? "",
      session.messages.at(-1)?.content ?? "",
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(keyword);
  });

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

  async function refreshSubjects() {
    try {
      const data = await fetchSubjects();
      setSubjects(data);
    } catch (error) {
      console.error("Failed to refresh notebooks:", error);
      showFeedback("error", "刷新笔记本列表失败，请稍后重试。");
    }
  }

  async function refreshSessions() {
    try {
      const data = await fetchSessions(DEFAULT_USER_ID);
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

  async function handleSaveProfile(payload: {
    agent_style_name: string;
    agent_style_prompt: string;
    onboarding_completed: boolean;
  }) {
    setIsSavingProfile(true);
    try {
      const nextProfile = await updateUserProfile(DEFAULT_USER_ID, payload);
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
    const nextName = draftDisplayName.trim();
    if (!nextName) {
      showFeedback("error", "昵称不能为空。");
      return;
    }

    setIsSavingDisplayName(true);
    try {
      const nextProfile = await updateUserProfile(DEFAULT_USER_ID, {
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

  async function handleGenerateNotebook(subject: Subject) {
    setGeneratingSubjectId(subject.id);
    try {
      const result = await generateKnowledgeBase(subject.id);
      await refreshSubjects();
      showFeedback(
        "success",
        `已为「${subject.name}」生成 ${result.chapters} 个基础章节。`
      );
    } catch (error) {
      console.error("生成基础内容失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "生成基础内容失败，请稍后重试。"
      );
    } finally {
      setGeneratingSubjectId(null);
    }
  }

  function handleOpenUpload(subjectId: string) {
    setPendingUploadSubjectId(subjectId);
    uploadInputRef.current?.click();
  }

  async function handleUploadSelectedFile(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const file = event.target.files?.[0];
    const subjectId = pendingUploadSubjectId;
    event.target.value = "";

    if (!file || !subjectId) {
      return;
    }

    setUploadingSubjectId(subjectId);
    try {
      const result = await uploadPDFWithSubject(file, subjectId);
      await refreshSubjects();
      showFeedback(
        "success",
        `已把 ${result.filename} 加入笔记本，共切分 ${result.total_chunks} 个知识块。`
      );
    } catch (error) {
      console.error("上传资料失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "上传资料失败，请稍后重试。"
      );
    } finally {
      setUploadingSubjectId(null);
      setPendingUploadSubjectId(null);
    }
  }

  async function handleDeleteNotebook(subject: Subject) {
    if (BUILTIN_NOTEBOOK_IDS.has(subject.id)) {
      showFeedback("info", "系统内置笔记本暂不支持删除。");
      return;
    }

    const confirmed = window.confirm(
      `确定删除笔记本「${subject.name}」吗？这会同时删除它关联的知识内容。`
    );
    if (!confirmed) {
      return;
    }

    setDeletingSubjectId(subject.id);
    try {
      await deleteSubject(subject.id);
      await refreshSubjects();
      showFeedback("success", `已删除笔记本「${subject.name}」`);
    } catch (error) {
      console.error("删除笔记本失败", error);
      showFeedback(
        "error",
        error instanceof Error ? error.message : "删除笔记本失败，请稍后重试。"
      );
    } finally {
      setDeletingSubjectId(null);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    const confirmed = window.confirm("确定删除这条聊天记录吗？删除后无法恢复。");
    if (!confirmed) {
      return;
    }

    setDeletingSessionId(sessionId);
    try {
      await deleteSession(DEFAULT_USER_ID, sessionId);
      await refreshSessions();
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
    const confirmed = window.confirm(
      "当前版本还没有真正的账号体系。点击确定后会清空这台设备上的学习缓存，并返回问答页。"
    );
    if (!confirmed) {
      return;
    }

    clearLearningStore();
    router.replace("/chat");
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
              ID: {DEFAULT_USER_ID}
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
            <span className="neo-label">我的笔记本</span>
          </div>
          <div className="neo-card-secondary neo-card-lift flex flex-col items-center justify-center gap-1 p-4">
            <span className="text-3xl font-black">{totalSources}</span>
            <span className="neo-label">总来源数</span>
          </div>
        </div>

        <div className="neo-card flex flex-col divide-y-4 divide-neo-ink">
          <div className="group my-[-4px] flex flex-col">
            <button
              onClick={() => setShowKnowledgeBase(!showKnowledgeBase)}
              className="flex items-center justify-between bg-neo-secondary p-4 text-left transition-colors hover:bg-[#ffe399]/80"
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
                className={`transition-transform duration-200 ${
                  showKnowledgeBase ? "rotate-90" : "group-hover:translate-x-1"
                }`}
              />
            </button>
            {showKnowledgeBase && (
              <div className="animate-in slide-in-from-top-2 border-t-4 border-dashed border-neo-ink bg-neo-secondary p-4 duration-200">
                <div className="mb-4 grid grid-cols-1 gap-3">
                  <label className="block">
                    <span className="neo-label mb-2 block">搜索笔记本</span>
                    <input
                      value={notebookQuery}
                      onChange={(event) => setNotebookQuery(event.target.value)}
                      className="neo-input w-full"
                      placeholder="按名称、简介或 ID 搜索"
                    />
                  </label>

                  <label className="block">
                    <span className="neo-label mb-2 block">排序方式</span>
                    <div className="relative">
                      <select
                        value={notebookSort}
                        onChange={(event) => setNotebookSort(event.target.value)}
                        className="neo-input w-full appearance-none pr-12"
                      >
                        <option value="default">默认顺序</option>
                        <option value="sources-desc">来源最多优先</option>
                        <option value="name-asc">按名称排序</option>
                        <option value="custom-first">优先显示自建笔记本</option>
                      </select>
                      <Filter
                        size={16}
                        strokeWidth={2.8}
                        className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2"
                      />
                    </div>
                  </label>

                  <label className="block">
                    <span className="neo-label mb-2 block">来源筛选</span>
                    <div className="relative">
                      <select
                        value={notebookSourceFilter}
                        onChange={(event) => setNotebookSourceFilter(event.target.value)}
                        className="neo-input w-full appearance-none pr-12"
                      >
                        <option value="all">全部笔记本</option>
                        <option value="with-sources">只看有资料</option>
                        <option value="empty">只看空笔记本</option>
                      </select>
                      <Filter
                        size={16}
                        strokeWidth={2.8}
                        className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2"
                      />
                    </div>
                  </label>
                </div>

                <div className="flex flex-col gap-3">
                  {filteredSubjects.length === 0 && (
                    <div className="neo-card p-4 text-center">
                      <p className="text-sm font-bold">
                        没找到匹配的笔记本，换个关键词试试。
                      </p>
                    </div>
                  )}

                  {filteredSubjects.map((subject) => {
                    const isBuiltIn = BUILTIN_NOTEBOOK_IDS.has(subject.id);
                    const isGenerating = generatingSubjectId === subject.id;
                    const isUploading = uploadingSubjectId === subject.id;
                    const isDeleting = deletingSubjectId === subject.id;

                    return (
                      <div
                        key={subject.id}
                        className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xl">{subject.icon}</span>
                              <span className="truncate font-black text-neo-ink">
                                {subject.name}
                              </span>
                              {isBuiltIn && (
                                <span className="neo-badge bg-neo-muted">
                                  内置
                                </span>
                              )}
                            </div>
                            <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
                              {subject.description || "这个笔记本还没有写简介。"}
                            </p>
                          </div>
                          <span className="neo-badge whitespace-nowrap bg-neo-secondary">
                            {subject.doc_count ?? 0} 条来源
                          </span>
                        </div>

                        <div className="mt-3 grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            onClick={() => router.push(`/chat?subject=${subject.id}`)}
                            className="neo-button w-full justify-center px-3 py-2 text-xs"
                          >
                            去学习
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenUpload(subject.id)}
                            disabled={isUploading}
                            className="neo-button-ghost w-full justify-center px-3 py-2 text-xs"
                          >
                            <Upload size={14} strokeWidth={2.8} />
                            {isUploading ? "上传中" : "上传资料"}
                          </button>

                          {(subject.doc_count ?? 0) === 0 && (
                            <button
                              type="button"
                              onClick={() => handleGenerateNotebook(subject)}
                              disabled={isGenerating}
                              className="neo-button-secondary w-full justify-center px-3 py-2 text-xs"
                            >
                              <Sparkles size={14} strokeWidth={2.8} />
                              {isGenerating ? "生成中" : "生成基础内容"}
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => setEditingSubject(subject)}
                            className="neo-button-ghost w-full justify-center px-3 py-2 text-xs"
                          >
                            <PencilLine size={14} strokeWidth={2.8} />
                            编辑信息
                          </button>

                          {!isBuiltIn && (
                            <button
                              type="button"
                              onClick={() => handleDeleteNotebook(subject)}
                              disabled={isDeleting}
                              className="neo-button-ghost w-full justify-center border-neo-ink bg-white px-3 py-2 text-xs hover:bg-neo-accent"
                            >
                              <Trash2 size={14} strokeWidth={2.8} />
                              {isDeleting ? "删除中" : "删除笔记本"}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  <button
                    onClick={() => setShowCreateModal(true)}
                    className="neo-button mt-2 w-full py-3"
                  >
                    + 新建笔记本
                  </button>
                </div>
              </div>
            )}
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
                        value={historyFilterSubjectId}
                        onChange={(event) => setHistoryFilterSubjectId(event.target.value)}
                        className="neo-input w-full appearance-none pr-12"
                      >
                        <option value="all">全部笔记本</option>
                        {subjects.map((subject) => (
                          <option key={subject.id} value={subject.id}>
                            {subject.name}
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
                      const subject = subjects.find((item) => item.id === session.subjectId);
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
                                <span className="text-lg">{subject?.icon ?? "📚"}</span>
                                <p className="truncate text-sm font-black">
                                  {session.title}
                                </p>
                              </div>
                              <p className="mt-2 text-xs font-bold text-neo-ink/60">
                                {subject?.name ?? "未知笔记本"} · {dateString}
                              </p>
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
                                  `/chat?subject=${session.subjectId}&session=${session.id}`
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
                  onChange={handleModelChange}
                  onRetry={() => {
                    void loadModelConfig();
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

      <input
        ref={uploadInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleUploadSelectedFile}
      />

      {showCreateModal && (
        <CreateAgentModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            void refreshSubjects();
            showFeedback("success", "新笔记本已经创建好了。");
          }}
        />
      )}

      {editingSubject && (
        <EditNotebookModal
          subject={editingSubject}
          onClose={() => setEditingSubject(null)}
          onSuccess={(updatedSubject) => {
            setEditingSubject(null);
            setSubjects((previous) =>
              previous.map((item) =>
                item.id === updatedSubject.id ? updatedSubject : item
              )
            );
            showFeedback("success", `已更新笔记本「${updatedSubject.name}」`);
          }}
        />
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
