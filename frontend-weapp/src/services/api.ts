import Taro from "@tarojs/taro";
import { clearAuthSession, getAccessToken, getAuthUser, getRefreshToken, isAccessTokenExpired, persistAuthSession, updateAuthTokens } from "@/store/auth";
import {
  DEFAULT_NOTEBOOK_ID,
  type AuthTokenEnvelope,
  type ChatSession,
  type ChatSessionWire,
  type KnowledgeMasteryPayload,
  type LatestQuizPayload,
  type LearningCenterResponse,
  type Memory,
  type ModelHealth,
  type Notebook,
  type NotebookKnowledgeStatus,
  type OptionKey,
  type PracticeAttemptResult,
  type PracticePackPayload,
  type PracticePackResponse,
  type PracticeRecommendationPayload,
  type QuizItem,
  type UserProfile
} from "@/types/api";

const API_BASE = process.env.TARO_APP_API_BASE || "http://127.0.0.1:8000/api";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  data?: any;
  header?: Record<string, string>;
}

interface NotebookKnowledgeStatusWire {
  subject_id?: string;
  collection_name?: string;
  doc_count?: number;
  shared_doc_count?: number;
  personal_doc_count?: number;
  chapter_count?: number;
  exam_pattern_count?: number;
  question_count?: number;
  url_count?: number;
  pdf_count?: number;
  personal_pdf_count?: number;
  personal_url_count?: number;
  personal_ready?: boolean;
  embedding_ready?: boolean;
  coverage_score?: number;
  coverage_level?: NotebookKnowledgeStatus["coverage_level"];
  missing_doc_types?: unknown[];
  suggested_actions?: unknown[];
  retrieval_ready?: boolean;
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

function toApiCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function toStringList(value: unknown[] | undefined): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
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
  if (getAuthUser() && getAccessToken() && !isAccessTokenExpired()) {
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

export async function fetchNotebookKnowledgeStatus(notebookId: string): Promise<NotebookKnowledgeStatus> {
  const payload = await request<NotebookKnowledgeStatusWire>(
    `/notebooks/${encodeURIComponent(notebookId)}/knowledge/status`
  );
  const docCount = toApiCount(payload.doc_count);
  return {
    notebookId: payload.subject_id || notebookId,
    collection_name: payload.collection_name || "",
    doc_count: docCount,
    shared_doc_count:
      typeof payload.shared_doc_count === "number"
        ? toApiCount(payload.shared_doc_count)
        : docCount,
    personal_doc_count: toApiCount(payload.personal_doc_count),
    chapter_count: toApiCount(payload.chapter_count),
    exam_pattern_count: toApiCount(payload.exam_pattern_count),
    question_count: toApiCount(payload.question_count),
    url_count: toApiCount(payload.url_count),
    pdf_count: toApiCount(payload.pdf_count),
    personal_pdf_count: toApiCount(payload.personal_pdf_count),
    personal_url_count: toApiCount(payload.personal_url_count),
    personal_ready: Boolean(payload.personal_ready),
    embedding_ready: Boolean(payload.embedding_ready),
    coverage_score: toApiCount(payload.coverage_score),
    coverage_level: payload.coverage_level || (docCount > 0 ? "sparse" : "empty"),
    missing_doc_types: toStringList(payload.missing_doc_types),
    suggested_actions: toStringList(payload.suggested_actions),
    retrieval_ready:
      typeof payload.retrieval_ready === "boolean"
        ? payload.retrieval_ready
        : Boolean(payload.embedding_ready && docCount > 0)
  };
}

export function fetchUserMemory(userId: string): Promise<Memory> {
  return request<Memory>(`/users/${userId}/memory`);
}

export function fetchKnowledgeMastery(userId: string, notebookId = DEFAULT_NOTEBOOK_ID): Promise<KnowledgeMasteryPayload> {
  return request<KnowledgeMasteryPayload>(
    `/users/${userId}/knowledge/mastery?subject_id=${encodeURIComponent(notebookId)}`
  );
}

export function fetchLearningCenter(userId: string, notebookId?: string): Promise<LearningCenterResponse> {
  const suffix = notebookId ? `?subject_id=${encodeURIComponent(notebookId)}` : "";
  return request<LearningCenterResponse>(`/users/${userId}/learning-center${suffix}`);
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
      selected_option: payload.selectedOption as OptionKey
    }
  });
}

export function createPracticePack(payload: PracticePackPayload): Promise<PracticePackResponse> {
  return request<PracticePackResponse>("/practice/packs", {
    method: "POST",
    data: {
      user_id: payload.user_id,
      session_id: payload.session_id || "",
      subject_id: payload.subject_id || DEFAULT_NOTEBOOK_ID,
      request_text: payload.request_text,
      current_practice_question: payload.current_practice_question || null,
      last_practice_pack: payload.last_practice_pack || [],
      context: payload.context || {}
    }
  });
}

export function fetchUserProfile(userId: string): Promise<UserProfile> {
  return request<UserProfile>(`/users/${userId}/profile`);
}

export function updateUserProfile(
  userId: string,
  payload: Partial<Pick<UserProfile, "display_name" | "agent_style_name" | "agent_style_prompt" | "onboarding_completed">>
): Promise<UserProfile> {
  return request<UserProfile>(`/users/${userId}/profile`, {
    method: "PUT",
    data: payload
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

export async function fetchSessions(userId: string): Promise<ChatSession[]> {
  const sessions = await request<ChatSessionWire[]>(`/users/${userId}/sessions`);
  return sessions.map((session) => ({
    id: session.id,
    title: session.title,
    notebookId: session.subject_id,
    updatedAt: Date.parse(session.updated_at) || Date.now(),
    messageCount: Array.isArray(session.messages) ? session.messages.length : 0
  }));
}

export function deleteSession(userId: string, sessionId: string) {
  return request<{ message: string }>(`/users/${userId}/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export function fetchModelHealth(): Promise<ModelHealth> {
  return request<ModelHealth>("/settings/model/health");
}

export { API_BASE };
