"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import BottomNav from "@/components/BottomNav";
import {
  fetchNotebooks,
  fetchNotebookKnowledgeStatus,
  fetchPracticeRecommendations,
  fetchUserProfile,
  updateUserProfile,
  type Notebook,
  type NotebookKnowledgeStatus,
  type QuizItem,
  type UserProfile,
} from "@/lib/api";
import { loadStoredNotebookId } from "@/lib/learning-store";

function buildNotebookStatusLabel(notebook: Notebook, status?: NotebookKnowledgeStatus) {
  const personalCount = status?.personal_doc_count || 0;
  if (personalCount > 0) return `我的资料 ${personalCount} 条`;
  const sharedCount = status?.shared_doc_count ?? status?.doc_count ?? notebook.doc_count ?? 0;
  if (sharedCount > 0) return `内置资料 ${sharedCount} 条`;
  return "内置笔记本";
}

export default function ProfilePage() {
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();
  const userId = user?.id ?? "";

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [notebookStatusById, setNotebookStatusById] = useState<Record<string, NotebookKnowledgeStatus>>({});
  const [recommendedPractice, setRecommendedPractice] = useState<QuizItem[]>([]);
  const [showRecommended, setShowRecommended] = useState(false);
  const [showEditName, setShowEditName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [isSavingName, setIsSavingName] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadProfile() {
    setLoading(true);
    setError("");
    try {
      const [notebookList] = await Promise.all([fetchNotebooks()]);
      setNotebooks(notebookList);
      // Load knowledge statuses
      const entries = await Promise.allSettled(
        notebookList.map(async (nb): Promise<[string, NotebookKnowledgeStatus] | null> => {
          try { return [nb.id, await fetchNotebookKnowledgeStatus(nb.id)]; } catch { return null; }
        })
      );
      const nextStatus: Record<string, NotebookKnowledgeStatus> = {};
      entries.forEach((r) => { if (r.status === "fulfilled" && r.value) nextStatus[r.value[0]] = r.value[1]; });
      setNotebookStatusById(nextStatus);

      fetchUserProfile(userId).then(setProfile).catch(() => {});
      fetchPracticeRecommendations(userId).then((r) => setRecommendedPractice(r.items)).catch(() => setRecommendedPractice([]));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isLoading || !userId) return;
    void loadProfile();
  }, [isLoading, userId]);

  async function handleSaveDisplayName() {
    const nextName = draftName.trim();
    if (!nextName || !userId) return;
    setIsSavingName(true);
    try {
      const nextProfile = await updateUserProfile(userId, { display_name: nextName });
      setProfile(nextProfile);
      setShowEditName(false);
    } catch {} finally { setIsSavingName(false); }
  }

  async function handleLogout() {
    if (!confirm("退出后需要重新登录才能使用问答、刷题和学习中心。确认退出？")) return;
    await logout();
    router.push("/login");
  }

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-3 sm:px-4">
        <div className="neo-card-secondary w-full p-4 sm:p-5 text-center animate-fade-in">
          <p className="text-base sm:text-lg font-black">正在加载...</p>
        </div>
      </div>
    );
  }

  const displayName = profile?.display_name?.trim() || user.display_name || "学习者";
  const currentNotebook = notebooks.find((n) => n.id === loadStoredNotebookId());

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <main className="flex-1 overflow-y-auto px-3 sm:px-4 pt-3 sm:pt-4 pb-[calc(104px+var(--safe-area-bottom))] safe-area-top">
        <h1 className="text-2xl sm:text-3xl font-black animate-fade-in">我的</h1>
        <p className="mt-1 text-[13px] sm:text-sm font-bold text-neo-ink/60">管理你的学习账号、知识库和练习推荐。</p>

        {/* ── 用户卡片 ── */}
        <div className="neo-card mt-3 sm:mt-4 flex items-center gap-3 sm:gap-4 p-3.5 sm:p-5 animate-slide-up">
          <div className="flex h-11 w-11 sm:h-14 sm:w-14 flex-shrink-0 items-center justify-center rounded-full border-2 sm:border-[3px] border-neo-ink bg-neo-accent text-xl sm:text-2xl font-black shadow-neo-xs sm:shadow-neo-sm">
            {displayName.slice(0, 1)}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg sm:text-xl font-black">{displayName}</h2>
            <p className="mt-0.5 sm:mt-1 truncate text-[11px] sm:text-xs font-bold text-neo-ink/60">{user.email || "H5 账号"}</p>
            {profile?.agent_style_name ? (
              <p className="mt-0.5 sm:mt-1 text-[11px] sm:text-xs font-bold text-neo-ink/70">风格：{profile.agent_style_name}</p>
            ) : null}
          </div>
          <button type="button" onClick={() => { setDraftName(displayName); setShowEditName(true); }} className="neo-button px-2.5 sm:px-3 py-1.5 sm:py-2 text-[11px] sm:text-xs">编辑</button>
        </div>

        {/* ── 统计 ── */}
        <div className="mt-3 sm:mt-4 grid grid-cols-2 gap-2 sm:gap-3" style={{ animationDelay: "0.05s" }}>
          <div className="neo-card-muted flex flex-col items-center justify-center gap-0.5 sm:gap-1 p-3 sm:p-4 animate-slide-up" style={{ animationDelay: "0.05s" }}>
            <span className="text-2xl sm:text-3xl font-black">{notebooks.length}</span>
            <span className="neo-label">知识库</span>
          </div>
          <div className="neo-card-secondary flex flex-col items-center justify-center gap-0.5 sm:gap-1 p-3 sm:p-4 animate-slide-up" style={{ animationDelay: "0.1s" }}>
            <span className="text-2xl sm:text-3xl font-black">{recommendedPractice.length}</span>
            <span className="neo-label">推荐题</span>
          </div>
        </div>

        {error ? <div className="neo-card-accent mt-3 sm:mt-4 p-3 sm:p-4"><p className="text-[13px] sm:text-sm font-bold">{error}</p></div> : null}

        {/* ── 推荐练习 ── */}
        <button type="button" onClick={() => setShowRecommended(!showRecommended)} className="neo-card mt-3 sm:mt-4 w-full p-3 sm:p-4 text-left animate-slide-up" style={{ animationDelay: "0.15s" }}>
          <div className="flex items-center justify-between">
            <div>
              <p className="neo-label">推荐练习</p>
              <p className="mt-0.5 sm:mt-1 text-[13px] sm:text-sm font-bold text-neo-ink/70">基于薄弱点优先推送真题</p>
            </div>
            <span className="neo-badge bg-neo-secondary">{recommendedPractice.length} 题</span>
          </div>
        </button>
        {showRecommended ? (
          <div className="neo-card mt-2 p-3 sm:p-4 animate-slide-up">
            {recommendedPractice.length === 0 ? (
              <p className="text-[13px] sm:text-sm font-bold text-neo-ink/60">暂无可推荐题目。</p>
            ) : (
              <>
                {recommendedPractice.slice(0, 3).map((item, idx) => (
                  <div key={item.question_id || idx} className="mt-2.5 sm:mt-3 border-2 sm:border-[3px] border-neo-ink bg-neo-bg p-2.5 sm:p-3 shadow-neo-xs sm:shadow-neo-sm first:mt-0 rounded-xl sm:rounded-2xl">
                    <div className="flex flex-wrap gap-1.5 sm:gap-2">
                      <span className="neo-badge bg-neo-accent">{item.difficulty || "练习"}</span>
                      <span className="neo-badge bg-white">{item.knowledge_point || "综合"}</span>
                    </div>
                    <p className="mt-1.5 sm:mt-2 text-[13px] sm:text-sm font-black leading-relaxed">{item.question}</p>
                  </div>
                ))}
                <button type="button" onClick={() => router.push("/practice")} className="neo-button mt-3 sm:mt-4 w-full justify-center">开始做这组推荐题</button>
              </>
            )}
          </div>
        ) : null}

        {/* ── 当前笔记本 ── */}
        <div className="neo-card mt-3 sm:mt-4 p-3 sm:p-4 animate-slide-up" style={{ animationDelay: "0.2s" }}>
          <p className="neo-label">当前笔记本</p>
          <p className="mt-1.5 sm:mt-2 text-sm sm:text-base font-black">{currentNotebook?.name || loadStoredNotebookId()}</p>
        </div>

        {/* ── 可用笔记本 ── */}
        <div className="neo-card mt-3 sm:mt-4 p-3 sm:p-4 animate-slide-up" style={{ animationDelay: "0.25s" }}>
          <p className="neo-label">可用笔记本</p>
          {loading ? <p className="mt-1.5 sm:mt-2 text-[13px] sm:text-sm font-bold text-neo-ink/60">正在加载...</p> : null}
          {notebooks.slice(0, 8).map((nb) => (
            <div key={nb.id} className="mt-2.5 sm:mt-3 border-b border-neo-ink/10 pb-2.5 sm:pb-3 last:border-0 last:pb-0">
              <p className="text-[13px] sm:text-sm font-black">{nb.icon || "📘"} {nb.name}</p>
              <p className="mt-0.5 sm:mt-1 text-[11px] sm:text-xs font-bold text-neo-ink/60">{nb.description || "暂无描述"}</p>
              <p className="mt-0.5 sm:mt-1 text-[11px] sm:text-xs font-bold text-neo-ink/50">{buildNotebookStatusLabel(nb, notebookStatusById[nb.id])}</p>
            </div>
          ))}
        </div>

        {/* ── 退出登录 ── */}
        <button type="button" onClick={handleLogout} className="neo-button-ghost mt-4 sm:mt-6 w-full justify-center py-3 sm:py-4 text-sm sm:text-base text-red-600 safe-area-bottom">
          退出登录
        </button>
      </main>

      {/* ── 编辑昵称 Modal ── */}
      {showEditName ? (
        <div className="neo-overlay flex items-center justify-center px-4 sm:px-6" onClick={() => setShowEditName(false)}>
          <div className="neo-card w-full max-w-sm bg-white p-4 sm:p-5 animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg sm:text-xl font-black">编辑昵称</h3>
            <input className="neo-input mt-3 sm:mt-4 w-full" value={draftName} maxLength={120} placeholder="例如：数据库冲刺中的小木" onChange={(e) => setDraftName(e.target.value)} />
            <div className="mt-3 sm:mt-4 flex gap-2 sm:gap-3">
              <button type="button" className="neo-button-ghost flex-1 justify-center" onClick={() => setShowEditName(false)}>取消</button>
              <button type="button" className="neo-button flex-1 justify-center" disabled={isSavingName} onClick={handleSaveDisplayName}>
                {isSavingName ? "保存中" : "保存"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <BottomNav />
    </div>
  );
}
