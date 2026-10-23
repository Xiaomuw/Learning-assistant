/**
 * 后端 API 封装
 * ==============
 * 统一管理所有后端接口调用，包括 SSE 流式请求。
 */

// ============================================================
// 类型定义
// ============================================================

export const DEFAULT_NOTEBOOK_ID = "data-structure";

/** 结构化讲解 */
export interface Explanation {
  topic: string;
  thinking: string;
  steps: string[];
  mistakes: string;
  similar: string[];
}

/** 练习题 */
export interface QuizOption {
  key: "A" | "B" | "C" | "D";
  text: string;
}

export interface QuizItem {
  difficulty: "基础" | "变式" | "易错";
  question: string;
  options: QuizOption[];
  correct_option: "A" | "B" | "C" | "D";
  explanation: string;
  option_rationales: Record<string, string>;
  knowledge_point: string;
  source_type: "question_bank" | "ai_generated";
  source_name: string;
  source_year?: number | null;
  question_id: string;
  hint?: string;
  subject_id?: string;
  notebook_id?: string;
  chapter_id?: string;
  topic_id?: string;
  concept_id?: string;
  concept_name?: string;
  source_session_id?: string;
}

export interface PracticeRecommendationPayload {
  notebookId: string;
  items: QuizItem[];
}

interface PracticeRecommendationWirePayload {
  subject_id: string;
  items: QuizItem[];
}

export interface MasteryScoreBreakdown {
  accuracy: number;
  completeness: number;
  understanding_depth: number;
  confidence: number;
  rag_doc_count: number;
  low_confidence: boolean;
  issues: string[];
}

export interface MasteryEvaluationResult {
  subject_id: string;
  knowledge_point: string;
  answer_type: "mcq" | "blank" | "short_answer";
  normalized_answer: string;
  is_correct: boolean;
  score: number;
  mastery_score: number;
  mastery_level: "mastered" | "learning" | "weak";
  weak_points: string[];
  feedback: string;
  score_breakdown: MasteryScoreBreakdown;
  retrieval_diagnosis: string;
  reference_doc_count: number;
}

export interface PracticeAttemptResult {
  is_correct: boolean;
  selected_option?: "A" | "B" | "C" | "D";
  correct_option: "A" | "B" | "C" | "D";
  explanation: string;
  option_rationales: Record<string, string>;
  memory: Memory;
  session_memory?: SessionPayload["session_memory"];
  mastery_evaluation?: MasteryEvaluationResult | null;
  personalized_feedback?: string;
}

export interface QuizRecommendedOption {
  label: string;
  value: string;
  source: "recent_topic" | "weak_point" | "default" | "current_context";
}

export interface QuizRequestResolution {
  is_quiz_request: boolean;
  action:
    | "generate_practice_pack"
    | "clarify_quiz_request"
    | "continue_practice"
    | "normal_qa";
  intent:
    | "quiz_generation"
    | "continue_quiz_generation"
    | "quiz_answer_check"
    | "normal_qa";
  topic: string | null;
  subject_id?: string | null;
  requested_topic?: string | null;
  previous_topic?: string | null;
  active_topic?: string | null;
  should_switch_topic?: boolean;
  topic_resolution_reason?: string;
  source:
    | "explicit_user_input"
    | "current_question"
    | "last_topic"
    | "recent_topic"
    | "weak_point"
    | "unknown";
  question_type:
    | "single_choice"
    | "multiple_choice"
    | "true_false"
    | "short_answer"
    | "mixed"
    | "unknown";
  difficulty: "easy" | "medium" | "hard" | "adaptive" | "unknown";
  count: number | null;
  target_module: "practice" | "qa";
  need_clarification: boolean;
  clarification_reason: string | null;
  recommended_options: QuizRecommendedOption[];
  custom_input_placeholder: string | null;
  reason: string;
}

export interface QuizClarificationPanel {
  title: string;
  description: string;
  recommended_options: QuizRecommendedOption[];
  question_type_options: QuizRecommendedOption[];
  difficulty_options: QuizRecommendedOption[];
  count_options: QuizRecommendedOption[];
  custom_input_placeholder: string;
}

/** 学习记忆 */
export interface Memory {
  weak_points: string[];
  error_count: Record<string, number>;
  recent_topics: string[];
  last_session?: string;
}

export interface KnowledgeMastery {
  user_id: string;
  subject_id: string;
  knowledge_point: string;
  exposure_count: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  mastery_score: number;
  mastery_level: "mastered" | "learning" | "weak";
  last_seen_at: string;
  last_practiced_at: string;
  updated_at: string;
}

export type LearningCenterStatus =
  | "unstarted"
  | "weak"
  | "learning"
  | "mastered";

export interface LearningCenterStatusCounts {
  unstarted: number;
  weak: number;
  learning: number;
  mastered: number;
}

export interface LearningCenterConcept {
  concept_id: string;
  concept_name: string;
  aliases: string[];
  importance: "high" | "medium" | "low";
  exam_frequency: "high" | "medium" | "low";
  prerequisites: string[];
  p_mastery: number;
  status: LearningCenterStatus;
  tested: boolean;
  test_status: "untested" | "tested";
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  question_count: number;
  last_practiced_at?: string | null;
  updated_at?: string | null;
}

export interface LearningCenterTopic {
  topic_id: string;
  topic_name: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  concepts: LearningCenterConcept[];
}

export interface LearningCenterChapter {
  chapter_id: string;
  chapter_name: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  topics: LearningCenterTopic[];
}

export interface LearningCenterSubject {
  subject_id: string;
  subject_name: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  chapters: LearningCenterChapter[];
}

export interface LearningCenterNextMove {
  subject_id: string;
  subject_name?: string | null;
  chapter_id?: string | null;
  chapter_name?: string | null;
  topic_id?: string | null;
  topic_name?: string | null;
  concept_id: string;
  concept_name: string;
  reason: string;
  status?: LearningCenterStatus | null;
  p_mastery?: number | null;
  recommended_action?: "qa" | "practice" | "review" | null;
}

export interface LearningCenterResponse {
  user_id: string;
  subjects: LearningCenterSubject[];
  next_move?: LearningCenterNextMove | null;
  generated_at?: string | null;
}

interface KnowledgeMasteryPayload {
  user_id: string;
  subject_id?: string | null;
  items: KnowledgeMastery[];
}

export function normalizeMemoryPayload(value: unknown): Memory {
  const payload =
    value && typeof value === "object"
      ? (value as Partial<Memory>)
      : {};

  const errorCount =
    payload.error_count && typeof payload.error_count === "object"
      ? Object.fromEntries(
          Object.entries(payload.error_count).map(([key, count]) => [
            key,
            typeof count === "number" && Number.isFinite(count) ? count : 0,
          ])
        )
      : {};

  return {
    weak_points: Array.isArray(payload.weak_points)
      ? payload.weak_points.filter((item): item is string => typeof item === "string")
      : [],
    error_count: errorCount,
    recent_topics: Array.isArray(payload.recent_topics)
      ? payload.recent_topics.filter((item): item is string => typeof item === "string")
      : [],
    last_session:
      typeof payload.last_session === "string" ? payload.last_session : "",
  };
}

/** 会话摘要（中期记忆） */
export interface SessionMemory {
  summaryText: string;
  activeTopic: string;
  currentGoal: string;
  openLoops: string[];
  resolvedPoints: string[];
  lastQuestionType: string;
  lastUpdatedAt: string;
}

export interface MessageProcessStage {
  key: string;
  label: string;
  status: "running" | "completed" | "failed";
  detail: string;
  elapsed?: number;
}

export interface MessageProcessExecution {
  mode?: string;
  degraded?: boolean;
  modelId?: string;
  modelFamily?: string;
  modelProvider?: string;
  primaryModelId?: string;
  fallbackModelId?: string;
  fallbackUsed?: boolean;
  fallbackReason?: string;
  modelAttempts?: Array<{
    model_id?: string;
    modelId?: string;
    role?: "primary" | "fallback" | string;
    status?: "ok" | "failed" | string;
    reason?: string;
  }>;
  streamingMode?: "node" | "token" | "none" | string;
  modelLatencyMs?: number;
}

export interface MessageProcessToolCall {
  name: string;
  label: string;
  success: boolean;
  argsSummary: string;
  error?: string;
  docCount?: number;
}

export interface MessageProcess {
  currentStage: string;
  stages: MessageProcessStage[];
  reasoningSummary?: string;
  reasoningTrace?: string;
  reasoningTraceEphemeral?: true;
  execution?: MessageProcessExecution;
  toolCalls?: MessageProcessToolCall[];
}

/** 聊天消息 */
export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  explanation?: Explanation;
  quiz?: QuizItem[];
  quizRequest?: QuizRequestResolution;
  quizClarification?: QuizClarificationPanel;
  process?: MessageProcess;
  questionType?: string;  // 路由分类结果，用于 ExplanationCard 差异化渲染
  route?: string;         // 执行路线 fast / explain / rag / agent
}

/** 聊天会话 */
export interface ChatSession {
  id: string;
  title: string;
  notebookId: string;
  updatedAt: number;
  messages: Message[];
  sessionMemory?: SessionMemory;
  latestQuiz?: QuizItem[];
}

/** SSE 事件 */
export interface SSEEvent {
  event: string;
  data: unknown;
}

export interface SendChatOptions {
  notebookId?: string;
  sessionId?: string;
  thinkingMode?: boolean;
  webSearchEnabled?: boolean;
  idleTimeoutMs?: number;
  maxConnectRetries?: number;
  onRetry?: (attempt: number, maxRetries: number) => void;
}

const CHAT_CONNECT_RETRY_STATUS = new Set([502, 503, 504]);

class ChatConnectionError extends Error {
  attempts: number;
  retryable: boolean;
  status?: number;
  receivedAnyEvent: boolean;
  reason?: string;

  constructor(
    message: string,
    {
      attempts,
      retryable,
      status,
      receivedAnyEvent = false,
      reason,
    }: {
      attempts: number;
      retryable: boolean;
      status?: number;
      receivedAnyEvent?: boolean;
      reason?: string;
    },
  ) {
    super(message);
    this.name = "ChatConnectionError";
    this.attempts = attempts;
    this.retryable = retryable;
    this.status = status;
    this.receivedAnyEvent = receivedAnyEvent;
    this.reason = reason;
  }
}

/** 笔记本 */
export interface Notebook {
  id: string;
  name: string;
  icon: string;
  description: string;
  doc_count: number;
  created_at: string;
}

export interface NotebookKnowledgeStatus {
  notebookId: string;
  collection_name: string;
  doc_count: number;
  shared_doc_count: number;
  personal_doc_count: number;
  chapter_count: number;
  exam_pattern_count: number;
  question_count: number;
  url_count: number;
  pdf_count: number;
  personal_pdf_count: number;
  personal_url_count: number;
  personal_ready: boolean;
  embedding_ready: boolean;
  coverage_score: number;
  coverage_level: "empty" | "sparse" | "partial" | "ready";
  missing_doc_types: string[];
  suggested_actions: string[];
  retrieval_ready: boolean;
}

interface NotebookKnowledgeStatusWire {
  subject_id: string;
  collection_name: string;
  doc_count: number;
  shared_doc_count?: number;
  personal_doc_count?: number;
  chapter_count: number;
  exam_pattern_count?: number;
  question_count: number;
  url_count: number;
  pdf_count: number;
  personal_pdf_count?: number;
  personal_url_count?: number;
  personal_ready?: boolean;
  embedding_ready: boolean;
  coverage_score?: number;
  coverage_level?: "empty" | "sparse" | "partial" | "ready";
  missing_doc_types?: string[];
  suggested_actions?: string[];
  retrieval_ready?: boolean;
}

/**
 * @deprecated 保留一轮兼容，前端页面和组件应统一使用 Notebook 语义。
 */
export type Subject = Notebook;

export interface NotebookUploadResult extends UploadResult {
  notebookId: string;
}

export interface NotebookUrlIngestResult {
  total_urls: number;
  successful_urls: number;
  total_chunks: number;
  notebookId: string;
  message: string;
}

interface NotebookUploadWireResult extends UploadResult {
  subject_id?: string;
}

interface NotebookUrlIngestWireResult {
  total_urls: number;
  successful_urls: number;
  total_chunks: number;
  subject_id?: string;
  message: string;
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
  model_switching_enabled?: boolean;
  model_switching_status?: string;
  locked_model?: string;
}

export interface ModelHealth {
  chat_model: string;
  chat_model_ok: boolean;
  chat_model_error?: string | null;
  model_switching_enabled?: boolean;
  model_switching_status?: string;
  supports_tool_calling?: boolean;
  supports_structured_output?: boolean;
}

/** 用户级 Agent 风格设置 */
export interface UserProfile {
  user_id: string;
  display_name: string;
  agent_style_name: string;
  agent_style_prompt: string;
  onboarding_completed: boolean;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

interface AuthEnvelope {
  user: AuthUser;
}

export interface RegisterCodeResponse {
  message: string;
  expires_in_seconds: number;
  resend_after_seconds: number;
}

// ============================================================
// 配置
// ============================================================

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

// ============================================================
// Auth — 登录 / 注册 / 当前用户
// ============================================================

export function fetchCurrentUser(): Promise<AuthEnvelope> {
  return request<AuthEnvelope>("/auth/me");
}

export function loginWithPassword(email: string, password: string): Promise<AuthEnvelope> {
  return request<AuthEnvelope>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password }),
    },
    false
  );
}

export function sendRegisterCode(email: string): Promise<RegisterCodeResponse> {
  return request<RegisterCodeResponse>(
    "/auth/register/send-code",
    {
      method: "POST",
      body: JSON.stringify({ email }),
    },
    false
  );
}

export function completeRegisterWithPassword(
  email: string,
  code: string,
  password: string,
  displayName?: string
): Promise<AuthEnvelope> {
  return request<AuthEnvelope>(
    "/auth/register/complete",
    {
      method: "POST",
      body: JSON.stringify({
        email,
        code,
        password,
        display_name: displayName?.trim() || undefined,
      }),
    },
    false
  );
}

export function registerWithPassword(
  email: string,
  code: string,
  password: string,
  displayName?: string
): Promise<AuthEnvelope> {
  return completeRegisterWithPassword(email, code, password, displayName);
}

export function logoutSession(): Promise<{ message: string }> {
  return request<{ message: string }>(
    "/auth/logout",
    {
      method: "POST",
    },
    false
  );
}

export function changePasswordWithCurrentSession(
  currentPassword: string,
  newPassword: string
): Promise<AuthEnvelope> {
  return request<AuthEnvelope>(
    "/auth/change-password",
    {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    },
    false
  );
}

// ============================================================
// 通用请求
// ============================================================

async function request<T>(
  path: string,
  options?: RequestInit,
  allowRefreshRetry = true,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...options,
  });

  if (
    res.status === 401 &&
    allowRefreshRetry &&
    !path.startsWith("/auth/login") &&
    !path.startsWith("/auth/register") &&
    !path.startsWith("/auth/refresh") &&
    !path.startsWith("/auth/logout")
  ) {
    const refreshed = await refreshAuthSession();
    if (refreshed) {
      return request<T>(path, options, false);
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiErrorDetail(err.detail ?? err.error ?? res.statusText));
  }
  return res.json() as Promise<T>;
}

let refreshPromise: Promise<boolean> | null = null;

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg?: unknown }).msg ?? "");
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join("；");
    }
  }

  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }

  return "请求失败，请稍后重试。";
}

async function readErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => null);
    if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
    if (payload && typeof payload.error === "string" && payload.error.trim()) {
      return payload.error;
    }
    if (payload) {
      return JSON.stringify(payload);
    }
  }

  const text = await response.text().catch(() => "");
  if (text.trim()) {
    return text.trim();
  }

  return response.statusText || `请求失败（${response.status}）`;
}

function normalizeErrorMessage(error: unknown): string {
  if (error instanceof Error && typeof error.message === "string" && error.message.trim()) {
    return error.message.trim();
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    for (const key of ["message", "detail", "error", "reason"]) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
    }
  }
  return "连接学习引擎时出现未知错误。";
}

function buildChatConnectionFailureMessage(error: unknown, attempts: number): string {
  const message = normalizeErrorMessage(error);
  const retryText =
    attempts > 1 ? `已自动重试 ${attempts - 1} 次，仍无法连接学习引擎。` : "无法连接学习引擎。";
  return `${retryText}${message ? `原因：${message}` : ""} 请检查后端服务或稍后重试。`;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function refreshAuthSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((response) => response.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
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
  const idleTimeoutMs = options.idleTimeoutMs ?? 90000;
  const maxConnectRetries = Math.max(0, options.maxConnectRetries ?? 2);
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let finished = false;
  let receivedAnyEvent = false;

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
      const timeoutSeconds = Math.round(idleTimeoutMs / 1000);
      const message = receivedAnyEvent
        ? `处理超时：学习引擎处理时间较长，超过 ${timeoutSeconds} 秒没有新的进度。请稍后重试或换一种问法。`
        : `连接超时：超过 ${timeoutSeconds} 秒仍未连接到学习引擎。请检查后端服务或稍后重试。`;
      onError?.(
        new ChatConnectionError(
          message,
          {
            attempts: 1,
            retryable: false,
            receivedAnyEvent,
            reason: receivedAnyEvent ? "timeout" : "connect_timeout",
          }
        )
      );
    }, idleTimeoutMs);
  };

  scheduleIdleTimeout();

  const openStream = async (hasAuthRetried = false, connectAttempt = 0): Promise<Response> => {
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          user_id: userId,
          session_id: options.sessionId,
          question,
          subject_id: options.notebookId ?? DEFAULT_NOTEBOOK_ID,
          thinking_mode: Boolean(options.thinkingMode),
          allow_web: Boolean(options.webSearchEnabled),
        }),
        signal: controller.signal,
      });

      if (res.status === 401 && !hasAuthRetried) {
        const refreshed = await refreshAuthSession();
        if (refreshed) {
          return openStream(true, connectAttempt);
        }
      }

      if (
        CHAT_CONNECT_RETRY_STATUS.has(res.status) &&
        connectAttempt < maxConnectRetries
      ) {
        options.onRetry?.(connectAttempt + 1, maxConnectRetries);
        await wait(400 * (connectAttempt + 1));
        return openStream(hasAuthRetried, connectAttempt + 1);
      }

      return res;
    } catch (error) {
      if (
        !(error instanceof DOMException && error.name === "AbortError") &&
        connectAttempt < maxConnectRetries
      ) {
        options.onRetry?.(connectAttempt + 1, maxConnectRetries);
        await wait(400 * (connectAttempt + 1));
        return openStream(hasAuthRetried, connectAttempt + 1);
      }
      throw error;
    }
  };

  openStream()
    .then(async (res) => {
      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }
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
            receivedAnyEvent = true;
            let parsedData: unknown = raw;
            try {
              parsedData = JSON.parse(raw);
            } catch {
              parsedData = raw;
            }

            if (currentEvent === "error") {
              onEvent({ event: currentEvent || "message", data: parsedData });
              cleanup();
              return;
            }

            if (currentEvent === "done") {
              onEvent({ event: currentEvent || "message", data: parsedData });
              cleanup();
              onDone?.();
              return;
            }

            onEvent({ event: currentEvent || "message", data: parsedData });
          }
        }
      }

      cleanup();
      onDone?.();
    })
    .catch((err) => {
      cleanup();
      if (err.name !== "AbortError") {
        const attempts = maxConnectRetries + 1;
        const message = receivedAnyEvent
          ? `连接中断：学习引擎已经开始处理，本轮不会自动重发以避免重复执行。${normalizeErrorMessage(err)} 你可以直接手动重试。`
          : buildChatConnectionFailureMessage(err, attempts);
        onError?.(
          new ChatConnectionError(message, {
            attempts,
            retryable: !receivedAnyEvent,
            receivedAnyEvent,
            reason: receivedAnyEvent ? "stream_interrupted" : "connect_failed",
          })
        );
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
    credentials: "include",
  });

  if (res.status === 401 && (await refreshAuthSession())) {
    return uploadPDF(file);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail);
  }

  return res.json() as Promise<UploadResult>;
}

// ============================================================
// Notebooks — 笔记本管理
// Wire 兼容说明：后端公开路径仍是 /subjects，payload 仍使用 subject_id。
// 页面和组件层只应消费 notebook-first 类型与函数。
// ============================================================

/** 获取所有笔记本 */
export function fetchNotebooks(): Promise<Notebook[]> {
  return request<Notebook[]>("/subjects");
}

/**
 * @deprecated 普通用户已不能维护系统默认知识库；保留一轮仅用于 wire 兼容。
 */
export function createNotebook(
  name: string,
  icon?: string,
  description?: string
): Promise<Notebook> {
  return request<Notebook>("/subjects", {
    method: "POST",
    body: JSON.stringify({ name, icon, description }),
  });
}

/**
 * @deprecated 普通用户已不能维护系统默认知识库；保留一轮仅用于 wire 兼容。
 */
export function deleteNotebook(notebookId: string): Promise<{ message: string }> {
  return request<{ message: string }>(`/subjects/${notebookId}`, {
    method: "DELETE",
  });
}

/**
 * @deprecated 普通用户已不能维护系统默认知识库；保留一轮仅用于 wire 兼容。
 */
export function updateNotebook(
  notebookId: string,
  payload: Pick<Notebook, "name" | "icon" | "description">
): Promise<Notebook> {
  return request<Notebook>(`/subjects/${notebookId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/**
 * @deprecated 默认知识库由系统 seed/admin 维护；普通用户入口已禁用。
 */
export function generateNotebookKnowledgeBase(
  notebookId: string
): Promise<{ chapters: number; total_chunks: number; message: string }> {
  return request(`/subjects/${notebookId}/generate`, { method: "POST" });
}

export async function fetchNotebookKnowledgeStatus(
  notebookId: string
): Promise<NotebookKnowledgeStatus> {
  const payload = await request<NotebookKnowledgeStatusWire>(
    `/notebooks/${notebookId}/knowledge/status`
  );
  return {
    notebookId: payload.subject_id || notebookId,
    collection_name: payload.collection_name,
    doc_count: payload.doc_count,
    shared_doc_count:
      typeof payload.shared_doc_count === "number"
        ? payload.shared_doc_count
        : payload.doc_count,
    personal_doc_count:
      typeof payload.personal_doc_count === "number" ? payload.personal_doc_count : 0,
    chapter_count: payload.chapter_count,
    exam_pattern_count:
      typeof payload.exam_pattern_count === "number" ? payload.exam_pattern_count : 0,
    question_count: payload.question_count,
    url_count: payload.url_count,
    pdf_count: payload.pdf_count,
    personal_pdf_count:
      typeof payload.personal_pdf_count === "number" ? payload.personal_pdf_count : 0,
    personal_url_count:
      typeof payload.personal_url_count === "number" ? payload.personal_url_count : 0,
    personal_ready:
      typeof payload.personal_ready === "boolean" ? payload.personal_ready : false,
    embedding_ready: payload.embedding_ready,
    coverage_score:
      typeof payload.coverage_score === "number" ? payload.coverage_score : 0,
    coverage_level: payload.coverage_level ?? (payload.doc_count > 0 ? "sparse" : "empty"),
    missing_doc_types: Array.isArray(payload.missing_doc_types)
      ? payload.missing_doc_types.filter((item): item is string => typeof item === "string")
      : [],
    suggested_actions: Array.isArray(payload.suggested_actions)
      ? payload.suggested_actions.filter((item): item is string => typeof item === "string")
      : [],
    retrieval_ready:
      typeof payload.retrieval_ready === "boolean"
        ? payload.retrieval_ready
        : Boolean(payload.embedding_ready && payload.doc_count > 0),
  };
}

/** 上传 PDF 到指定笔记本 */
export async function uploadPDFToNotebook(
  file: File,
  notebookId: string
): Promise<NotebookUploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("subject_id", notebookId);

  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });

  if (res.status === 401 && (await refreshAuthSession())) {
    return uploadPDFToNotebook(file, notebookId);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail);
  }

  const payload = (await res.json()) as NotebookUploadWireResult;
  return {
    filename: payload.filename,
    total_pages: payload.total_pages,
    total_chunks: payload.total_chunks,
    message: payload.message,
    notebookId: payload.subject_id ?? notebookId,
  };
}

/** 上传网址集合到指定笔记本 */
export async function ingestNotebookUrls(
  notebookId: string,
  urls: string[]
): Promise<NotebookUrlIngestResult> {
  const payload = await request<NotebookUrlIngestWireResult>(`/upload/urls`, {
    method: "POST",
    body: JSON.stringify({ subject_id: notebookId, urls }),
  });

  return {
    total_urls: payload.total_urls,
    successful_urls: payload.successful_urls,
    total_chunks: payload.total_chunks,
    notebookId: payload.subject_id ?? notebookId,
    message: payload.message,
  };
}

/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const fetchSubjects = fetchNotebooks;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const createSubject = createNotebook;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const deleteSubject = deleteNotebook;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const updateSubject = updateNotebook;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const generateKnowledgeBase = generateNotebookKnowledgeBase;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const uploadPDFWithSubject = uploadPDFToNotebook;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first API。
 */
export const ingestUrls = ingestNotebookUrls;

// ============================================================
// User Data — 学习记忆 / 历史记录 / 最新题包
// ============================================================

interface SessionPayload {
  id: string;
  subject_id: string;
  title: string;
  messages: Message[];
  latest_quiz?: QuizItem[];
  session_memory?: {
    summary_text?: string;
    active_topic?: string;
    current_goal?: string;
    open_loops?: string[];
    resolved_points?: string[];
    last_question_type?: string;
    last_updated_at?: string;
  };
  updated_at: string;
}

interface LatestQuizPayload {
  session_id?: string;
  subject_id?: string;
  quiz_items: QuizItem[];
}

function normalizeStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => stripMarkdownArtifacts(String(item ?? "")))
      .filter((item) => item.length > 0);
  }

  if (typeof value === "string" && value.trim()) {
    return [stripMarkdownArtifacts(value)];
  }

  return [];
}

export function stripMarkdownArtifacts(value: string): string {
  return String(value ?? "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/(^|\s)#{1,6}\s*/g, "$1")
    .replace(/(^|\s)(?:-{3,}|\*{3,}|_{3,})(?=\s|$)/g, "$1")
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith("```"))
    .filter((line) => !/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line))
    .map((line) =>
      line
        .replace(/^\s{0,3}#{1,6}\s*/g, "")
        .replace(/^\s*[-*+]\s+/g, "")
        .replace(/^\s*\d+[\.)、]\s+/g, "")
        .replace(/^\s*>\s?/g, "")
        .replace(/\*\*|__|\*|_/g, "")
        .replace(/\s{2,}/g, " ")
        .trim()
    )
    .filter(Boolean)
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function normalizeExplanationPayload(
  payload?: Partial<Explanation> | null
): Explanation | undefined {
  if (!payload || typeof payload !== "object") {
    return undefined;
  }

  const normalized: Explanation = {
    topic: typeof payload.topic === "string" ? stripMarkdownArtifacts(payload.topic) : "",
    thinking: typeof payload.thinking === "string" ? stripMarkdownArtifacts(payload.thinking) : "",
    steps: normalizeStringList(payload.steps),
    mistakes: typeof payload.mistakes === "string" ? stripMarkdownArtifacts(payload.mistakes) : "",
    similar: normalizeStringList(payload.similar),
  };

  if (
    !normalized.topic &&
    !normalized.thinking &&
    normalized.steps.length === 0 &&
    !normalized.mistakes &&
    normalized.similar.length === 0
  ) {
    return undefined;
  }

  return normalized;
}

function normalizeMessagePayload(payload: unknown): Message | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const message = payload as Partial<Message> & {
    question_type?: unknown;
    quiz_request?: unknown;
    quiz_clarification?: unknown;
  };
  const role = message.role === "assistant" ? "assistant" : "user";
  const content = typeof message.content === "string" ? stripMarkdownArtifacts(message.content) : "";
  const timestamp =
    typeof message.timestamp === "number" ? message.timestamp : Date.now();
  const questionType =
    typeof message.questionType === "string"
      ? message.questionType
      : typeof message.question_type === "string"
        ? message.question_type
        : undefined;
  const route = typeof message.route === "string" ? message.route : undefined;

  return {
    role,
    content,
    timestamp,
    explanation: normalizeExplanationPayload(message.explanation),
    quiz: Array.isArray(message.quiz) ? message.quiz : undefined,
    quizRequest:
      message.quizRequest && typeof message.quizRequest === "object"
        ? (message.quizRequest as QuizRequestResolution)
        : message.quiz_request && typeof message.quiz_request === "object"
          ? (message.quiz_request as QuizRequestResolution)
        : undefined,
    quizClarification:
      message.quizClarification && typeof message.quizClarification === "object"
        ? (message.quizClarification as QuizClarificationPanel)
        : message.quiz_clarification && typeof message.quiz_clarification === "object"
          ? (message.quiz_clarification as QuizClarificationPanel)
        : undefined,
    process:
      message.process && typeof message.process === "object"
        ? (message.process as MessageProcess)
        : undefined,
    questionType,
    route,
  };
}

function normalizeSessionMemory(
  sessionMemory?: SessionPayload["session_memory"] | null
): SessionMemory | undefined {
  if (!sessionMemory || typeof sessionMemory !== "object") {
    return undefined;
  }

  const normalized: SessionMemory = {
    summaryText:
      typeof sessionMemory.summary_text === "string"
        ? sessionMemory.summary_text
        : "",
    activeTopic:
      typeof sessionMemory.active_topic === "string"
        ? sessionMemory.active_topic
        : "",
    currentGoal:
      typeof sessionMemory.current_goal === "string"
        ? sessionMemory.current_goal
        : "",
    openLoops: Array.isArray(sessionMemory.open_loops)
      ? sessionMemory.open_loops.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0
        )
      : [],
    resolvedPoints: Array.isArray(sessionMemory.resolved_points)
      ? sessionMemory.resolved_points.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0
        )
      : [],
    lastQuestionType:
      typeof sessionMemory.last_question_type === "string"
        ? sessionMemory.last_question_type
        : "",
    lastUpdatedAt:
      typeof sessionMemory.last_updated_at === "string"
        ? sessionMemory.last_updated_at
        : "",
  };

  if (
    !normalized.summaryText &&
    !normalized.activeTopic &&
    !normalized.currentGoal &&
    normalized.openLoops.length === 0 &&
    normalized.resolvedPoints.length === 0
  ) {
    return undefined;
  }

  return normalized;
}

export function fetchUserMemory(userId: string): Promise<Memory> {
  return request<unknown>(`/users/${userId}/memory`).then(normalizeMemoryPayload);
}

export function fetchKnowledgeMastery(
  userId: string,
  notebookId?: string
): Promise<KnowledgeMastery[]> {
  const params = new URLSearchParams();
  if (notebookId) {
    params.set("subject_id", notebookId);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<KnowledgeMasteryPayload>(
    `/users/${userId}/knowledge/mastery${suffix}`
  ).then((payload) => (Array.isArray(payload.items) ? payload.items : []));
}

export function fetchLearningCenter(
  userId: string,
  subjectId?: string
): Promise<LearningCenterResponse> {
  const params = new URLSearchParams();
  if (subjectId) {
    params.set("subject_id", subjectId);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<LearningCenterResponse>(
    `/users/${userId}/learning-center${suffix}`
  );
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
    notebookId: session.subject_id,
    updatedAt: Date.parse(session.updated_at) || Date.now(),
    messages: Array.isArray(session.messages)
      ? session.messages
          .map((message) => normalizeMessagePayload(message))
          .filter((message): message is Message => Boolean(message))
      : [],
    sessionMemory: normalizeSessionMemory(session.session_memory),
    latestQuiz: Array.isArray(session.latest_quiz) ? session.latest_quiz : [],
  }));
}

export function deleteSession(userId: string, sessionId: string) {
  return request<{ message: string }>(`/users/${userId}/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function fetchLatestQuiz(userId: string): Promise<QuizItem[]> {
  const payload = await request<LatestQuizPayload>(`/users/${userId}/quiz/latest`);
  return Array.isArray(payload.quiz_items) ? payload.quiz_items : [];
}

export async function fetchLatestQuizBundle(
  userId: string
): Promise<{ sessionId: string; notebookId: string; quizItems: QuizItem[] }> {
  const payload = await request<LatestQuizPayload>(`/users/${userId}/quiz/latest`);
  return {
    sessionId: typeof payload.session_id === "string" ? payload.session_id : "",
    notebookId:
      typeof payload.subject_id === "string" ? payload.subject_id : DEFAULT_NOTEBOOK_ID,
    quizItems: Array.isArray(payload.quiz_items) ? payload.quiz_items : [],
  };
}

export function fetchPracticeRecommendations(
  userId: string,
  notebookId?: string
): Promise<PracticeRecommendationPayload> {
  const search = new URLSearchParams();
  if (notebookId) {
    search.set("subject_id", notebookId);
  }

  const suffix = search.toString() ? `?${search.toString()}` : "";
  return request<PracticeRecommendationWirePayload>(
    `/users/${userId}/practice/recommendations${suffix}`
  ).then((payload) => ({
    notebookId: payload.subject_id,
    items: Array.isArray(payload.items) ? payload.items : [],
  }));
}

export function submitPracticeAttempt(payload: {
  user_id: string;
  session_id?: string;
  subject_id?: string;
  quiz_item: QuizItem;
  selected_option: "A" | "B" | "C" | "D";
}): Promise<PracticeAttemptResult> {
  return request<PracticeAttemptResult>("/practice/attempts", {
    method: "POST",
    body: JSON.stringify({
      user_id: payload.user_id,
      session_id: payload.session_id,
      subject_id: payload.subject_id,
      quiz_item: payload.quiz_item,
      selected_option: payload.selected_option,
    }),
  });
}

export function createPracticePack(payload: {
  user_id: string;
  session_id?: string;
  subject_id?: string;
  request_text: string;
  current_practice_question?: QuizItem | null;
  last_practice_pack?: QuizItem[];
  context?: Record<string, unknown>;
}): Promise<{
  subject_id: string;
  quiz_request: QuizRequestResolution;
  quiz_clarification?: QuizClarificationPanel | null;
  items: QuizItem[];
  generation_status?: Record<string, unknown>;
  errors?: Array<Record<string, unknown>>;
  message?: string;
}> {
  return request<{
    subject_id: string;
    quiz_request: QuizRequestResolution;
    quiz_clarification?: QuizClarificationPanel | null;
    items: QuizItem[];
    generation_status?: Record<string, unknown>;
    errors?: Array<Record<string, unknown>>;
    message?: string;
  }>("/practice/packs", {
    method: "POST",
    body: JSON.stringify({
      user_id: payload.user_id,
      session_id: payload.session_id,
      subject_id: payload.subject_id ?? DEFAULT_NOTEBOOK_ID,
      request_text: payload.request_text,
      current_practice_question: payload.current_practice_question,
      last_practice_pack: payload.last_practice_pack ?? [],
      context: payload.context ?? {},
    }),
  });
}

// ============================================================
// Model Config — 模型切换
// ============================================================

export function normalizeModelConfig(config: ModelConfig): ModelConfig {
  if (config.model_switching_enabled === true) {
    return config;
  }

  const lockedModelId = config.locked_model || config.current_model;
  const lockedModel =
    config.available_models.find((item) => item.id === lockedModelId) ??
    config.available_models.find((item) => item.id === config.current_model) ?? {
      id: lockedModelId,
      label: lockedModelId,
      provider: "OpenAI",
      family: "GPT",
    };

  return {
    ...config,
    current_model: lockedModel.id,
    available_models: [lockedModel],
    model_switching_enabled: false,
    model_switching_status: config.model_switching_status ?? "development",
    locked_model: lockedModel.id,
  };
}

export function fetchModelConfig(): Promise<ModelConfig> {
  return request<ModelConfig>("/settings/model").then(normalizeModelConfig);
}

export function updateModelConfig(chatModel: string): Promise<ModelConfig> {
  return request<ModelConfig>("/settings/model", {
    method: "PUT",
    body: JSON.stringify({ chat_model: chatModel }),
  }).then(normalizeModelConfig);
}

export function fetchModelHealth(): Promise<ModelHealth> {
  return request<ModelHealth>("/settings/model/health");
}
