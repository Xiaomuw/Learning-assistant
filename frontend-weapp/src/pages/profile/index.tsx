import { useState } from "react";
import Taro, { useDidShow } from "@tarojs/taro";
import { Button, Input, Text, View } from "@tarojs/components";
import {
  fetchCurrentUser,
  fetchNotebookKnowledgeStatus,
  fetchNotebooks,
  fetchPracticeRecommendations,
  fetchUserProfile,
  logoutWechatMini,
  updateUserProfile
} from "@/services/api";
import { clearAuthSession, getAuthUser, getRefreshToken, requireAuthUser } from "@/store/auth";
import { clearLearningDataForUser, getStoredNotebookId } from "@/store/learning";
import type { AuthUser, Notebook, NotebookKnowledgeStatus, QuizItem, UserProfile } from "@/types/api";
import "./index.scss";

function buildNotebookStatusLabel(notebook: Notebook, status?: NotebookKnowledgeStatus) {
  const personalCount = status?.personal_doc_count || 0;
  if (personalCount > 0) {
    return `我的资料 ${personalCount} 条`;
  }

  const sharedCount = status?.shared_doc_count ?? status?.doc_count ?? notebook.doc_count ?? 0;
  if (sharedCount > 0) {
    return `内置资料 ${sharedCount} 条`;
  }

  return "内置笔记本";
}

export default function ProfilePage() {
  const [user, setUser] = useState<AuthUser | null>(getAuthUser());
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

  useDidShow(() => {
    const current = requireAuthUser();
    if (!current) return;
    loadProfile(current.id);
  });

  async function loadProfile(userId: string) {
    setLoading(true);
    setError("");
    try {
      const [me, notebookList] = await Promise.all([
        fetchCurrentUser(),
        fetchNotebooks()
      ]);
      setUser(me.user);
      setNotebooks(notebookList);
      setNotebookStatusById({});
      loadNotebookKnowledgeStatuses(notebookList);

      fetchUserProfile(userId)
        .then((p) => setProfile(p))
        .catch(() => {});

      fetchPracticeRecommendations(userId, getStoredNotebookId())
        .then((r) => setRecommendedPractice(Array.isArray(r.items) ? r.items : []))
        .catch(() => setRecommendedPractice([]));
    } catch (err: any) {
      setError(err?.message || "个人信息加载失败");
      setUser(getAuthUser());
    } finally {
      setLoading(false);
    }
  }

  async function loadNotebookKnowledgeStatuses(notebookList: Notebook[]) {
    if (!notebookList.length) {
      setNotebookStatusById({});
      return;
    }

    const entries = await Promise.all(
      notebookList.map(async (notebook): Promise<[string, NotebookKnowledgeStatus] | null> => {
        try {
          const status = await fetchNotebookKnowledgeStatus(notebook.id);
          return [notebook.id, status];
        } catch {
          return null;
        }
      })
    );
    const nextStatusById: Record<string, NotebookKnowledgeStatus> = {};
    entries.forEach((entry) => {
      if (entry) {
        nextStatusById[entry[0]] = entry[1];
      }
    });
    setNotebookStatusById(nextStatusById);
  }

  async function handleSaveDisplayName() {
    const userId = user?.id;
    if (!userId) return;
    const nextName = draftName.trim();
    if (!nextName) {
      Taro.showToast({ title: "昵称不能为空", icon: "none" });
      return;
    }
    setIsSavingName(true);
    try {
      const nextProfile = await updateUserProfile(userId, { display_name: nextName });
      setProfile(nextProfile);
      setUser((prev) => (prev ? { ...prev, display_name: nextProfile.display_name } : prev));
      setShowEditName(false);
      Taro.showToast({ title: "昵称已更新", icon: "success" });
    } catch (err: any) {
      Taro.showToast({ title: err?.message || "保存失败", icon: "none" });
    } finally {
      setIsSavingName(false);
    }
  }

  function handleLogout() {
    Taro.showModal({
      title: "退出当前账号？",
      content: "退出后需要重新登录才能使用问答、刷题和学习中心。",
      confirmText: "确认退出",
      confirmColor: "#ff5252",
      cancelText: "取消"
    }).then(async (result) => {
      if (!result.confirm) return;
      const refreshToken = getRefreshToken();
      const userId = getAuthUser()?.id;
      try {
        if (refreshToken) await logoutWechatMini(refreshToken);
      } catch {}
      clearLearningDataForUser(userId);
      clearAuthSession();
      Taro.reLaunch({ url: "/pages/login/index" });
    });
  }

  const displayName = profile?.display_name?.trim() || user?.display_name || "学习者";
  const recommendedCount = recommendedPractice.length;
  const currentNotebook = notebooks.find((item) => item.id === getStoredNotebookId());

  return (
    <View className="page profile-page">
      <Text className="page-title">我的</Text>
      <Text className="page-subtitle">管理你的学习账号、知识库和练习推荐。</Text>

      {/* ── 用户卡片 ── */}
      <View className="card profile-card">
        <View className="avatar">{displayName.slice(0, 1)}</View>
        <View className="profile-main">
          <Text className="profile-name">{displayName}</Text>
          <Text className="profile-email">{user?.email || "微信小程序账号"}</Text>
          {profile?.agent_style_name ? (
            <Text className="profile-style">风格：{profile.agent_style_name}</Text>
          ) : null}
        </View>
        <Button
          className="edit-button"
          onClick={() => {
            setDraftName(displayName);
            setShowEditName(true);
          }}
        >
          编辑
        </Button>
      </View>

      {/* ── 统计概览 ── */}
      <View className="stat-grid">
        <View className="card stat-card stat-a">
          <Text className="stat-number">{notebooks.length}</Text>
          <Text className="stat-label">知识库</Text>
        </View>
        <View className="card stat-card stat-b">
          <Text className="stat-number">{recommendedCount}</Text>
          <Text className="stat-label">推荐题</Text>
        </View>
      </View>

      {error ? (
        <View className="card error-card">
          <Text>{error}</Text>
        </View>
      ) : null}

      {/* ── 推荐练习题 ── */}
      <View className="card section-card" onClick={() => setShowRecommended(!showRecommended)}>
        <View className="section-header">
          <View>
            <Text className="section-title">推荐练习</Text>
            <Text className="section-desc">基于薄弱点优先推送真题，适合快速热身。</Text>
          </View>
          <View className="section-badge">
            <Text className="badge-text">{recommendedPractice.length} 题</Text>
          </View>
        </View>
        {showRecommended ? (
          <View className="recommended-body">
            {recommendedPractice.length === 0 ? (
              <Text className="empty-text">暂无可推荐题目，先去问答页生成题包。</Text>
            ) : (
              <View>
                {recommendedPractice.slice(0, 3).map((item, idx) => (
                  <View key={`${item.question_id || idx}`} className="quiz-preview-card">
                    <View className="quiz-preview-tags">
                      <Text className="tag accent">{item.difficulty || "练习"}</Text>
                      <Text className="tag secondary">{item.knowledge_point || "综合"}</Text>
                    </View>
                    <Text className="quiz-preview-text">{item.question}</Text>
                  </View>
                ))}
                <Button
                  className="button-primary go-practice-button"
                  onClick={(e) => {
                    e.stopPropagation();
                    Taro.switchTab({ url: "/pages/practice/index" });
                  }}
                >
                  开始做这组推荐题
                </Button>
              </View>
            )}
          </View>
        ) : null}
      </View>

      {/* ── 当前笔记本 ── */}
      <View className="card section-card">
        <Text className="section-title">当前笔记本</Text>
        <Text className="section-value">{currentNotebook?.name || getStoredNotebookId()}</Text>
        <Text className="section-desc">小程序 MVP 只提供使用已有笔记本，管理请前往 H5 端。</Text>
      </View>

      {/* ── 可用笔记本 ── */}
      <View className="card section-card">
        <Text className="section-title">可用笔记本</Text>
        {loading ? <Text className="section-desc">正在加载...</Text> : null}
        {notebooks.slice(0, 8).map((notebook) => (
          <View key={notebook.id} className="notebook-row">
            <Text className="notebook-name">{notebook.icon || "📘"} {notebook.name}</Text>
            <Text className="notebook-desc">{notebook.description || "暂无描述"}</Text>
            <Text className="notebook-meta">
              {buildNotebookStatusLabel(notebook, notebookStatusById[notebook.id])}
            </Text>
          </View>
        ))}
      </View>

      {/* ── 版本范围 ── */}
      <View className="card section-card">
        <Text className="section-title">版本范围</Text>
        <Text className="section-desc">
          当前小程序第一版包含微信登录、问答、刷题、学习中心和个人页；PDF/URL 入库、模型配置和 Notebook 管理后续再加。
        </Text>
      </View>

      {/* ── 退出登录 ── */}
      <Button className="button-secondary logout-button" onClick={handleLogout}>
        退出登录
      </Button>

      <Text className="team-credit">第六组：方励志、周江杰、黄思炜、朱高辉_Agent学习助手</Text>

      {/* ── 编辑昵称 Modal ── */}
      {showEditName ? (
        <View className="modal-overlay" onClick={() => setShowEditName(false)}>
          <View className="modal-card" onClick={(e) => e.stopPropagation()}>
            <Text className="modal-title">编辑昵称</Text>
            <Input
              className="modal-input"
              value={draftName}
              maxlength={120}
              placeholder="例如：数据库冲刺中的小木"
              onInput={(e: any) => setDraftName(e.detail.value)}
            />
            <View className="modal-actions">
              <Button className="button-secondary modal-btn" onClick={() => setShowEditName(false)}>
                取消
              </Button>
              <Button
                className="button-primary modal-btn"
                loading={isSavingName}
                disabled={isSavingName}
                onClick={handleSaveDisplayName}
              >
                {isSavingName ? "保存中" : "保存"}
              </Button>
            </View>
          </View>
        </View>
      ) : null}
    </View>
  );
}
