import Taro from "@tarojs/taro";
import { clearAuthSession, getAccessToken, getAuthUser, getRefreshToken, persistAuthSession, updateAuthTokens } from "@/store/auth";
import { DEFAULT_NOTEBOOK_ID, type AuthTokenEnvelope, type KnowledgeMasteryPayload, type LatestQuizPayload, type Memory, type Notebook, type PracticeAttemptResult, type PracticeRecommendationPayload, type QuizItem } from "@/types/api";

const API_BASE = process.env.TARO_APP_API_BASE || "http://127.0.0.1:8000/api";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  data?: any;
  header?: Record<string, string>;
}

function buildHeaders(extraHeader: Record<string, string> = {}) {
  const token = getAccessToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extraHeader
  };
}

function formatApiError(data: any, statusCode: number) {
  if (typeof data?.detail === "string") return data.detail;
  if (data?.detail && typeof data.detail === "object") {
    if (typeof data.detail.message === "string") return data.detail.message;
    if (typeof data.detail.reason === "string") return data.detail.reason;
  }
  if (typeof data?.error === "string") return data.error;
  if (typeof data?.message === "string") return data.message;
  return `请求失败（${statusCode}）`;
}

let refreshPromise: Promise<boolean> | null = null;

export async function refreshAuthSession(): Promise<boolean> {
  if (!refreshPromise) {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;

    refreshPromise = Taro.request<AuthTokenEnvelope>({
      url: `${API_BASE}/auth/wechat-mini/refresh`,
      method: "POST",
      data: { refresh_token: refreshToken },
      header: { "Content-Type": "application/json" }
    })
      .then((response) => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          persistAuthSession(response.data);
          return true;
        }
        return false;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

export async function request<T>(path: string, options: RequestOptions = {}, allowRefresh = true): Promise<T> {
  const response = await Taro.request<T>({
    url: `${API_BASE}${path}`,
    method: options.method || "GET",
    data: options.data,
    header: buildHeaders(options.header)
  });

  if (response.statusCode === 401 && allowRefresh) {
    const refreshed = await refreshAuthSession();
    if (refreshed) {
      return request<T>(path, options, false);
    }
    clearAuthSession();
    Taro.reLaunch({ url: "/pages/login/index" });
    throw new Error("登录已过期，请重新登录");
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(formatApiError(response.data, response.statusCode));
  }

  return response.data;
}

export async function ensureAuthSession(): Promise<boolean> {
  if (getAuthUser() && getAccessToken()) {
    return true;
  }
  const refreshed = await refreshAuthSession();
  if (!refreshed) {
    clearAuthSession();
    Taro.reLaunch({ url: "/pages/login/index" });
  }
  return refreshed;
}

export async function loginWithWechatCode(code: string, displayName?: string): Promise<AuthTokenEnvelope> {
  const payload = await request<AuthTokenEnvelope>(
    "/auth/wechat-mini/login",
    {
      method: "POST",
      data: {
        code,
        display_name: displayName?.trim() || undefined
      }
    },
    false
  );
  updateAuthTokens(payload);
  persistAuthSession(payload);
  return payload;
}

export function fetchCurrentUser() {
  return request<{ user: AuthTokenEnvelope["user"] }>("/auth/me");
}

export function fetchNotebooks(): Promise<Notebook[]> {
  return request<Notebook[]>("/subjects");
}

export function fetchUserMemory(userId: string): Promise<Memory> {
  return request<Memory>(`/users/${userId}/memory`);
}

export function fetchKnowledgeMastery(userId: string, notebookId = DEFAULT_NOTEBOOK_ID): Promise<KnowledgeMasteryPayload> {
  return request<KnowledgeMasteryPayload>(
    `/users/${userId}/knowledge/mastery?subject_id=${encodeURIComponent(notebookId)}`
  );
}

export function fetchLatestQuizBundle(userId: string): Promise<LatestQuizPayload> {
  return request<LatestQuizPayload>(`/users/${userId}/quiz/latest`);
}

export function fetchPracticeRecommendations(userId: string, notebookId = DEFAULT_NOTEBOOK_ID): Promise<PracticeRecommendationPayload> {
  return request<PracticeRecommendationPayload>(
    `/users/${userId}/practice/recommendations?subject_id=${encodeURIComponent(notebookId)}`
  );
}

export function submitPracticeAttempt(payload: {
  userId: string;
  sessionId: string;
  notebookId: string;
  quizItem: QuizItem;
  selectedOption: string;
}): Promise<PracticeAttemptResult> {
  return request<PracticeAttemptResult>("/practice/attempts", {
    method: "POST",
    data: {
      user_id: payload.userId,
      session_id: payload.sessionId,
      subject_id: payload.notebookId,
      quiz_item: payload.quizItem,
      selected_option: payload.selectedOption
    }
  });
}

export function logoutWechatMini(refreshToken: string) {
  return request<{ message: string }>(
    "/auth/wechat-mini/logout",
    {
      method: "POST",
      data: { refresh_token: refreshToken }
    },
    false
  );
}

export { API_BASE };
