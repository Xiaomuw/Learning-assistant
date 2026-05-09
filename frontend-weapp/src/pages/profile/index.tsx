import { useState } from "react";
import Taro, { useDidShow } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { fetchCurrentUser, fetchNotebooks, logoutWechatMini } from "@/services/api";
import { clearAuthSession, getAuthUser, getRefreshToken, requireAuthUser } from "@/store/auth";
import { clearChatDraft, clearStoredQuiz, clearStoredSessionId, getStoredNotebookId } from "@/store/learning";
import type { AuthUser, Notebook } from "@/types/api";
import "./index.scss";

export default function ProfilePage() {
  const [user, setUser] = useState<AuthUser | null>(getAuthUser());
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useDidShow(() => {
    const current = requireAuthUser();
    if (!current) return;
    loadProfile();
  });

  async function loadProfile() {
    setLoading(true);
    setError("");
    try {
      const [me, notebookList] = await Promise.all([
        fetchCurrentUser(),
        fetchNotebooks()
      ]);
      setUser(me.user);
      setNotebooks(notebookList);
    } catch (err: any) {
      setError(err?.message || "个人信息加载失败");
      setUser(getAuthUser());
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    const refreshToken = getRefreshToken();
    try {
      if (refreshToken) {
        await logoutWechatMini(refreshToken);
      }
    } catch {
      // 退出以本地会话清理为准，服务端撤销失败时允许用户重新登录。
    } finally {
      clearAuthSession();
      clearStoredSessionId();
      clearStoredQuiz();
      clearChatDraft();
      Taro.reLaunch({ url: "/pages/login/index" });
    }
  }

  const currentNotebook = notebooks.find((item) => item.id === getStoredNotebookId());

  return (
    <View className="page profile-page">
      <Text className="page-title">我的</Text>
      <Text className="page-subtitle">管理当前小程序端登录状态和学习入口。</Text>

      <View className="card profile-card">
        <View className="avatar">{(user?.display_name || "学").slice(0, 1)}</View>
        <View className="profile-main">
          <Text className="profile-name">{user?.display_name || "学习者"}</Text>
          <Text className="profile-email">{user?.email || "微信小程序账号"}</Text>
        </View>
      </View>

      {error ? (
        <View className="card error-card">
          <Text>{error}</Text>
        </View>
      ) : null}

      <View className="card section-card">
        <Text className="section-title">当前笔记本</Text>
        <Text className="section-value">{currentNotebook?.name || getStoredNotebookId()}</Text>
        <Text className="section-desc">小程序 MVP 只提供切换和使用已有笔记本，Notebook 管理仍在 H5 端完成。</Text>
      </View>

      <View className="card section-card">
        <Text className="section-title">可用笔记本</Text>
        {loading ? <Text className="section-desc">正在加载...</Text> : null}
        {notebooks.slice(0, 8).map((notebook) => (
          <View key={notebook.id} className="notebook-row">
            <Text className="notebook-name">{notebook.icon || "📘"} {notebook.name}</Text>
            <Text className="notebook-desc">{notebook.description || "暂无描述"}</Text>
          </View>
        ))}
      </View>

      <View className="card section-card">
        <Text className="section-title">版本范围</Text>
        <Text className="section-desc">
          当前小程序第一版包含微信登录、问答、刷题、学习中心和个人页；PDF/URL 入库、模型配置和 Notebook 管理后续再加。
        </Text>
      </View>

      <Button className="button-secondary logout-button" onClick={logout}>
        退出登录
      </Button>
    </View>
  );
}
