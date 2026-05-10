import Taro from "@tarojs/taro";
import type { AuthTokenEnvelope, AuthUser } from "@/types/api";

const ACCESS_TOKEN_KEY = "la_weapp_access_token";
const REFRESH_TOKEN_KEY = "la_weapp_refresh_token";
const USER_KEY = "la_weapp_user";
const ACTIVE_USER_KEY = "la_weapp_active_user_id";

export function getAccessToken(): string {
  return Taro.getStorageSync(ACCESS_TOKEN_KEY) || "";
}

export function getRefreshToken(): string {
  return Taro.getStorageSync(REFRESH_TOKEN_KEY) || "";
}

export function getAuthUser(): AuthUser | null {
  return Taro.getStorageSync(USER_KEY) || null;
}

export function persistAuthSession(payload: AuthTokenEnvelope) {
  Taro.setStorageSync(ACCESS_TOKEN_KEY, payload.access_token);
  Taro.setStorageSync(REFRESH_TOKEN_KEY, payload.refresh_token);
  Taro.setStorageSync(USER_KEY, payload.user);
  Taro.setStorageSync(ACTIVE_USER_KEY, payload.user.id);
}

export function updateAuthTokens(payload: Pick<AuthTokenEnvelope, "access_token" | "refresh_token">) {
  Taro.setStorageSync(ACCESS_TOKEN_KEY, payload.access_token);
  Taro.setStorageSync(REFRESH_TOKEN_KEY, payload.refresh_token);
}

export function clearAuthSession() {
  Taro.removeStorageSync(ACCESS_TOKEN_KEY);
  Taro.removeStorageSync(REFRESH_TOKEN_KEY);
  Taro.removeStorageSync(USER_KEY);
  Taro.removeStorageSync(ACTIVE_USER_KEY);
}

export function requireAuthUser(): AuthUser | null {
  const user = getAuthUser();
  const token = getAccessToken();
  if (!user || !token) {
    Taro.reLaunch({ url: "/pages/login/index" });
    return null;
  }
  Taro.setStorageSync(ACTIVE_USER_KEY, user.id);
  return user;
}

export function getAuthSnapshot(): { user: AuthUser | null; accessToken: string; refreshToken: string } {
  return {
    user: getAuthUser(),
    accessToken: getAccessToken(),
    refreshToken: getRefreshToken()
  };
}
