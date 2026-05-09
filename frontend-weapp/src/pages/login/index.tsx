import { useState } from "react";
import Taro, { useLoad } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { getAccessToken, getAuthUser, persistAuthSession } from "@/store/auth";
import { loginWithWechatCode } from "@/services/api";
import "./index.scss";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useLoad(() => {
    if (getAccessToken() && getAuthUser()) {
      Taro.switchTab({ url: "/pages/chat/index" });
    }
  });

  async function handleLogin() {
    if (loading) return;
    setLoading(true);
    setError("");

    try {
      const loginResult = await Taro.login({ timeout: 10000 });
      if (!loginResult.code) {
        throw new Error("微信登录没有返回 code，请稍后重试");
      }
      const session = await loginWithWechatCode(loginResult.code, "微信学习者");
      persistAuthSession(session);
      Taro.showToast({ title: "登录成功", icon: "success" });
      setTimeout(() => {
        Taro.switchTab({ url: "/pages/chat/index" });
      }, 400);
    } catch (err: any) {
      setError(err?.message || "登录失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <View className="page login-page">
      <View className="login-hero">
        <Text className="login-kicker">Learning Assistant</Text>
        <Text className="page-title">用微信打开你的学习助手</Text>
        <Text className="page-subtitle">
          登录后可以继续使用聊天讲解、智能出题、刷题反馈和掌握度记录。
        </Text>
      </View>

      <View className="card login-card">
        <Text className="login-card-title">微信一键登录</Text>
        <Text className="login-card-desc">
          小程序会使用微信登录凭证创建或找回你的学习账号。
        </Text>
        {error ? <Text className="login-error">{error}</Text> : null}
        <Button className="button-primary login-button" loading={loading} onClick={handleLogin}>
          {loading ? "登录中..." : "微信登录"}
        </Button>
      </View>
    </View>
  );
}
