/**
 * 后端 API 封装
 * ==============
 * 统一管理所有后端接口调用，包括 SSE 流式请求。
 */

// ============================================================
// 类型定义
// ============================================================

/** 结构化讲解 */
export interface Explanation {
  topic: string;
  thinking: string;
  steps: string[] | string;
  mistakes: string[] | string;
  similar: string[] | string;
}

/** 练习题 */
export interface QuizItem {
  difficulty: "基础" | "变式" | "易错";
  question: string;
  hint: string;
  answer: string;
  knowledge_point: string;
}

/** 学习记忆 */
export interface Memory {
  weak_points: string[];
  error_count: Record<string, number>;
  recent_topics: string[];
  last_session?: string;
}

/** 聊天消息 */
export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  explanation?: Explanation;
  quiz?: QuizItem[];
}

/** 聊天会话 */
export interface ChatSession {
  id: string;
  title: string;
  subjectId: string;
  updatedAt: number;
  messages: Message[];
  latestQuiz?: QuizItem[];
}

/** SSE 事件 */
export interface SSEEvent {
  event: string;
  data: unknown;
}

export interface SendChatOptions {
  subjectId?: string;
  sessionId?: string;
  idleTimeoutMs?: number;
}

/** 学科 */
export interface Subject {
  id: string;
  name: string;
  icon: string;
  description: string;
  doc_count: number;
  created_at: string;
}

/** 可选聊天模型 */
export interface SelectableModel {
  id: string;
  label: string;
  provider: string;
  family: string;
}

/** 模型配置 */
export interface ModelConfig {
  current_model: string;
  embedding_model: string;
  available_models: SelectableModel[];
}

/** 用户级 Agent 风格设置 */
export interface UserProfile {
  user_id: string;
  display_name: string;
  agent_style_name: string;
  agent_style_prompt: string;
  onboarding_completed: boolean;
}

// ============================================================
// 配置
// ============================================================

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
export const DEFAULT_USER_ID =
  process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "default_user";

// ============================================================
// 通用请求
// ============================================================

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "请求失败");
  }
  return res.json() as Promise<T>;
}

// ============================================================
// Chat — SSE 流式请求
// ============================================================

/**
 * 发起 SSE 流式聊天请求
 *
 * @param userId  用户 ID
 * @param question  用户问题
 * @param onEvent  每个 SSE 事件的回调
 * @param onDone   流结束回调
 * @param onError  错误回调
 */
export function sendChatSSE(
  userId: string,
  question: string,
  onEvent: (event: SSEEvent) => void,
  onDone?: () => void,
  onError?: (error: Error) => void,
  options: SendChatOptions = {},
): AbortController {
  const controller = new AbortController();
  const idleTimeoutMs = options.idleTimeoutMs ?? 45000;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let finished = false;

  const cleanup = () => {
    finished = true;
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  const scheduleIdleTimeout = () => {
    if (finished || idleTimeoutMs <= 0) {
      return;
    }

    if (timeoutId) {
      clearTimeout(timeoutId);
    }

    timeoutId = setTimeout(() => {
      if (finished) {
        return;
      }

      controller.abort("idle-timeout");
      cleanup();
      onError?.(
        new Error(
          `本次请求超过 ${Math.round(idleTimeoutMs / 1000)} 秒没有收到新内容，已自动结束，你可以直接重试。`
        )
      );
    }, idleTimeoutMs);
  };

  scheduleIdleTimeout();

  fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: userId,
      session_id: options.sessionId,
      question,
      subject_id: options.subjectId ?? "general",
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error("SSE 请求失败");
      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        scheduleIdleTimeout();

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const raw = line.slice(5).trim();
            try {
              const data = JSON.parse(raw);
              onEvent({ event: currentEvent || "message", data });
            } catch {
              onEvent({ event: currentEvent || "message", data: raw });
            }
          }
        }
      }

      cleanup();
      onDone?.();
    })
    .catch((err) => {
      cleanup();
      if (err.name !== "AbortError") {
        onError?.(err);
      }
    });

  return controller;
}

// ============================================================
// Upload — 文件上传
// ============================================================

export interface UploadResult {
  filename: string;
  total_pages: number;
  total_chunks: number;
  message: string;
}

/**
 * 上传 PDF 文件到后端
 */
export async function uploadPDF(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail);
  }

  return res.json() as Promise<UploadResult>;
}

// ============================================================
// Subjects — 学科管理
// ============================================================

/** 获取所有学科 */
export function fetchSubjects(): Promise<Subject[]> {
  return request<Subject[]>("/subjects");
}

/** 创建新学科 */
export function createSubject(
  name: string,
  icon?: string,
  description?: string
): Promise<Subject> {
  return request<Subject>("/subjects", {
    method: "POST",
    body: JSON.stringify({ name, icon, description }),
  });
}

/** 删除指定学科 / 笔记本 */
export function deleteSubject(subjectId: string): Promise<{ message: string }> {
  return request<{ message: string }>(`/subjects/${subjectId}`, {
    method: "DELETE",
  });
}

/** 更新指定学科 / 笔记本 */
export function updateSubject(
  subjectId: string,
  payload: Pick<Subject, "name" | "icon" | "description">
): Promise<Subject> {
  return request<Subject>(`/subjects/${subjectId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** 自动生成学科知识框架 */
export function generateKnowledgeBase(
  subjectId: string
): Promise<{ chapters: number; total_chunks: number; message: string }> {
  return request(`/subjects/${subjectId}/generate`, { method: "POST" });
}

/** 上传 PDF 到指定学科 */
export async function uploadPDFWithSubject(
  file: File,
  subjectId: string
): Promise<UploadResult & { subject_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("subject_id", subjectId);

  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail);
  }

  return res.json();
}

/** 上传网址集合到指定学科 */
export async function ingestUrls(
  subjectId: string,
  urls: string[]
): Promise<{ total_urls: number; successful_urls: number; total_chunks: number; subject_id: string; message: string }> {
  return request(`/upload/urls`, {
    method: "POST",
    body: JSON.stringify({ subject_id: subjectId, urls }),
  });
}

// ============================================================
// User Data — 学习记忆 / 历史记录 / 最新题包
// ============================================================

interface SessionPayload {
  id: string;
  subject_id: string;
  title: string;
  messages: Message[];
  latest_quiz?: QuizItem[];
  updated_at: string;
}

export function fetchUserMemory(userId: string): Promise<Memory> {
  return request<Memory>(`/users/${userId}/memory`);
}

export function fetchUserProfile(userId: string): Promise<UserProfile> {
  return request<UserProfile>(`/users/${userId}/profile`);
}

export function updateUserProfile(
  userId: string,
  payload: Partial<
    Pick<
      UserProfile,
      "display_name" | "agent_style_name" | "agent_style_prompt" | "onboarding_completed"
    >
  >
): Promise<UserProfile> {
  return request<UserProfile>(`/users/${userId}/profile`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function fetchSessions(userId: string): Promise<ChatSession[]> {
  const sessions = await request<SessionPayload[]>(`/users/${userId}/sessions`);
  return sessions.map((session) => ({
    id: session.id,
    title: session.title,
    subjectId: session.subject_id,
    updatedAt: Date.parse(session.updated_at) || Date.now(),
    messages: Array.isArray(session.messages) ? session.messages : [],
    latestQuiz: Array.isArray(session.latest_quiz) ? session.latest_quiz : [],
  }));
}

export function deleteSession(userId: string, sessionId: string) {
  return request<{ message: string }>(`/users/${userId}/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function fetchLatestQuiz(userId: string): Promise<QuizItem[]> {
  const payload = await request<{ quiz_items: QuizItem[] }>(
    `/users/${userId}/quiz/latest`
  );
  return Array.isArray(payload.quiz_items) ? payload.quiz_items : [];
}

// ============================================================
// Model Config — 模型切换
// ============================================================

export function fetchModelConfig(): Promise<ModelConfig> {
  return request<ModelConfig>("/settings/model");
}

export function updateModelConfig(chatModel: string): Promise<ModelConfig> {
  return request<ModelConfig>("/settings/model", {
    method: "PUT",
    body: JSON.stringify({ chat_model: chatModel }),
  });
}
