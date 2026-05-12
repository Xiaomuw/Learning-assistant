import { useRef, useState } from "react";
import Taro, { useLoad } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { getAccessToken, getAuthUser, getRefreshToken } from "@/store/auth";
import { ensureAuthSession, loginWithWechatCode } from "@/services/api";
import "./index.scss";

function readableLoginError(error: any) {
  const raw = String(error?.message || error?.errMsg || "").trim();
  const message = raw.toLowerCase();
  if (!raw) return "登录失败，请稍后重试";
  if (message.includes("missing_config") || /微信小程序登录未配置|wechat_mini_app/.test(raw)) {
    return "微信登录配置还没有生效，请检查后端小程序配置后重试。";
  }
  if (message.includes("code_used") || raw.includes("凭证已使用") || raw.includes("凭证已过期")) {
    return "本次微信登录凭证已过期，请重新点击微信登录。";
  }
  if (message.includes("invalid_code") || raw.includes("凭证无效")) {
    return "微信登录凭证无效，请重新点击微信登录。";
  }
  if (message.includes("risk_blocked") || raw.includes("风险") || raw.includes("登录暂时不可用")) {
    return "当前微信登录存在风险拦截，请稍后重试或联系管理员。";
  }
  if (message.includes("timeout") || raw.includes("超时")) {
    return "登录请求超时，请检查网络后重试。";
  }
  if (
    message.includes("wechat_unavailable") ||
    message.includes("request:fail") ||
    raw.includes("服务暂时不可用")
  ) {
    return "微信登录服务暂时不可用，请稍后重试。";
  }
  if (message.includes("401") || message.includes("unauthorized") || raw.includes("登录已过期")) {
    return "登录状态已过期，请重新登录。";
  }
  return raw;
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const loginInFlightRef = useRef(false);

  useLoad(() => {
    void restoreExistingSession();
  });

  async function restoreExistingSession() {
    if (!getAuthUser() || (!getAccessToken() && !getRefreshToken())) return;
    const ready = await ensureAuthSession();
    if (ready) {
      Taro.switchTab({ url: "/pages/chat/index" });
    }
  }

  async function handleLogin() {
    if (loginInFlightRef.current) return;
    loginInFlightRef.current = true;
    setLoading(true);
    setError("");

    try {
      const loginResult = await Taro.login({ timeout: 10000 });
      if (!loginResult.code) {
        throw new Error("微信登录没有返回 code，请稍后重试");
      }
      await loginWithWechatCode(loginResult.code, "微信学习者");
      Taro.showToast({ title: "登录成功", icon: "success" });
      setTimeout(() => {
        Taro.switchTab({ url: "/pages/chat/index" });
      }, 400);
    } catch (err: any) {
      setError(readableLoginError(err));
    } finally {
      loginInFlightRef.current = false;
      setLoading(false);
    }
  }

  function handleAgreementTap() {
    Taro.showToast({ title: "用户协议内容待补充", icon: "none" });
  }

  function handlePrivacyTap() {
    Taro.showToast({ title: "隐私政策内容待补充", icon: "none" });
  }

  return (
    <View className="page login-page">
      <View className="login-hero">
        <Text className="login-kicker">LEARNING ASSISTANT</Text>
        <Text className="login-title">
          用微信登录<Text className="login-title-product">学习助手</Text>
        </Text>
        <Text className="login-subtitle">
          登录后可继续使用聊天讲解、智能出题、刷题反馈和掌握度记录。
        </Text>
      </View>

      <View className="card login-card">
        <Text className="login-card-title">微信一键登录</Text>
        <Text className="login-card-desc">
          我们将使用微信登录凭证创建或找回你的学习账号。
        </Text>
        {error ? <Text className="login-error">{error}</Text> : null}
        <Button className="button-primary login-button" loading={loading} disabled={loading} onClick={handleLogin}>
          {loading ? "登录中..." : "使用微信一键登录"}
        </Button>
        <View className="login-agreement">
          <Text className="login-agreement-text">登录即代表你同意</Text>
          <Text className="login-agreement-link" onClick={handleAgreementTap}>
            《用户协议》
          </Text>
          <Text className="login-agreement-text">和</Text>
          <Text className="login-agreement-link" onClick={handlePrivacyTap}>
            《隐私政策》
          </Text>
        </View>
      </View>
    </View>
  );
}
