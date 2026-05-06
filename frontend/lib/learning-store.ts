import { normalizeModelConfig } from "@/lib/api";
import type {
  ChatSession,
  MasteryEvaluationResult,
  Memory,
  ModelConfig,
  QuizItem,
} from "@/lib/api";

/**
 * 前端本地学习态的唯一迁移边界。
 *
 * 新写入统一使用 notebook-first key 和 notebookId；旧 subject key/shape
 * 只在这里读取兼容，避免历史数据兼容逻辑扩散到页面和组件层。
 */
const MEMORY_KEY = "learning_memory";
const QUIZ_KEY = "learning_quiz";
const QUIZ_META_KEY = "learning_quiz_meta";
const PRACTICE_STATE_KEY = "learning_practice_state";
const LEGACY_SUBJECT_KEY = "learning_subject_id";
const NOTEBOOK_KEY = "learning_notebook_id";
const SESSIONS_KEY = "learning_chat_sessions";
const MODEL_CONFIG_KEY = "learning_model_config";
const ACTIVE_USER_KEY = "learning_active_user_id";
export const DEFAULT_NOTEBOOK_ID = "data-structure";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

function isBrowser() {
  return typeof window !== "undefined";
}

function getActiveUserId(): string | null {
  if (!isBrowser()) {
    return null;
  }

  const value = window.localStorage.getItem(ACTIVE_USER_KEY)?.trim();
  return value ? value : null;
}

function scopedKey(baseKey: string, userId: string) {
  return `${baseKey}:${userId}`;
}

function readStoreItem(baseKey: string): string | null {
  if (!isBrowser()) {
    return null;
  }

  const userId = getActiveUserId();
  if (userId) {
    return window.localStorage.getItem(scopedKey(baseKey, userId));
  }

  return window.localStorage.getItem(baseKey);
}

function writeStoreItem(baseKey: string, value: string) {
  if (!isBrowser()) {
    return;
  }

  const userId = getActiveUserId();
  const key = userId ? scopedKey(baseKey, userId) : baseKey;
  window.localStorage.setItem(key, value);
}

function removeStoreItem(baseKey: string, userId?: string | null) {
  if (!isBrowser()) {
    return;
  }

  const activeUserId = userId ?? getActiveUserId();
  if (activeUserId) {
    window.localStorage.removeItem(scopedKey(baseKey, activeUserId));
  }

  window.localStorage.removeItem(baseKey);
}

function safeParse<T>(value: string | null, fallback: T): T {
  if (!value) {
    return fallback;
  }

  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export function normalizeStoredNotebookId(
  notebookId: string | null | undefined,
  fallbackId = DEFAULT_NOTEBOOK_ID
) {
  const normalized = notebookId?.trim();
  if (!normalized || normalized === "general") {
    return fallbackId;
  }

  return normalized;
}

export function loadStoredMemory(): Memory {
  if (!isBrowser()) {
    return EMPTY_MEMORY;
  }

  const stored = safeParse<Partial<Memory>>(
    readStoreItem(MEMORY_KEY),
    {}
  );

  return {
    weak_points: Array.isArray(stored.weak_points) ? stored.weak_points : [],
    error_count:
      stored.error_count && typeof stored.error_count === "object"
        ? stored.error_count
        : {},
    recent_topics: Array.isArray(stored.recent_topics)
      ? stored.recent_topics
      : [],
    last_session: stored.last_session ?? "",
  };
}

export function persistMemory(memory: Memory) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(MEMORY_KEY, JSON.stringify(memory));
}

export function loadStoredQuiz(): QuizItem[] {
  if (!isBrowser()) {
    return [];
  }

  const stored = safeParse<QuizItem[]>(readStoreItem(QUIZ_KEY), []);
  return Array.isArray(stored) ? stored : [];
}

export interface StoredQuizMeta {
  topic?: string;
  subjectId?: string;
  sessionId?: string;
  quizSignature?: string;
  createdAt?: number;
  updatedAt?: number;
  shouldSwitchTopic?: boolean;
}

export function buildQuizSignature(quizList: QuizItem[]) {
  return quizList
    .map((item, index) => `${item.question_id || index}:${item.question}:${item.correct_option}`)
    .join("|");
}

export function loadStoredQuizMeta(): StoredQuizMeta | null {
  if (!isBrowser()) {
    return null;
  }

  const stored = safeParse<Partial<StoredQuizMeta> | null>(
    readStoreItem(QUIZ_META_KEY),
    null
  );
  if (!stored || typeof stored !== "object") {
    return null;
  }

  return {
    topic: typeof stored.topic === "string" ? stored.topic : undefined,
    subjectId: typeof stored.subjectId === "string" ? normalizeStoredNotebookId(stored.subjectId) : undefined,
    sessionId: typeof stored.sessionId === "string" ? stored.sessionId : undefined,
    quizSignature: typeof stored.quizSignature === "string" ? stored.quizSignature : undefined,
    createdAt: Number.isFinite(stored.createdAt) ? Number(stored.createdAt) : undefined,
    updatedAt: Number.isFinite(stored.updatedAt) ? Number(stored.updatedAt) : undefined,
    shouldSwitchTopic: Boolean(stored.shouldSwitchTopic),
  };
}

export function persistQuiz(quiz: QuizItem[], meta?: StoredQuizMeta) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(QUIZ_KEY, JSON.stringify(quiz));
  if (meta) {
    const now = Date.now();
    writeStoreItem(
      QUIZ_META_KEY,
      JSON.stringify({
        ...meta,
        subjectId: normalizeStoredNotebookId(meta.subjectId),
        quizSignature: meta.quizSignature || buildQuizSignature(quiz),
        createdAt: meta.createdAt || now,
        updatedAt: now,
      })
    );
  }
}

export function clearStoredQuiz() {
  if (!isBrowser()) {
    return;
  }

  removeStoreItem(QUIZ_KEY);
  removeStoreItem(QUIZ_META_KEY);
}

export interface StoredPracticeFeedback {
  isCorrect: boolean;
  correctOption: "A" | "B" | "C" | "D";
  explanation: string;
  optionRationales: Record<string, string>;
  masteryEvaluation?: MasteryEvaluationResult | null;
  personalizedFeedback?: string;
}

export interface StoredPracticeState {
  quizSignature: string;
  topic?: string;
  subjectId?: string;
  currentIndex: number;
  selectedOption: "A" | "B" | "C" | "D" | null;
  showHint: boolean;
  feedback: StoredPracticeFeedback | null;
  sessionId: string;
  notebookId: string;
  isCompleted?: boolean;
  completedAt?: number | null;
  updatedAt: number;
}

function isOptionKey(value: unknown): value is "A" | "B" | "C" | "D" {
  return value === "A" || value === "B" || value === "C" || value === "D";
}

export function loadStoredPracticeState(): StoredPracticeState | null {
  if (!isBrowser()) {
    return null;
  }

  const stored = safeParse<Partial<StoredPracticeState> | null>(
    readStoreItem(PRACTICE_STATE_KEY),
    null
  );

  if (!stored || typeof stored !== "object" || typeof stored.quizSignature !== "string") {
    return null;
  }

  const feedback =
    stored.feedback &&
    typeof stored.feedback === "object" &&
    typeof stored.feedback.isCorrect === "boolean" &&
    isOptionKey(stored.feedback.correctOption) &&
    typeof stored.feedback.explanation === "string"
      ? {
          isCorrect: stored.feedback.isCorrect,
          correctOption: stored.feedback.correctOption,
          explanation: stored.feedback.explanation,
          optionRationales:
            stored.feedback.optionRationales &&
            typeof stored.feedback.optionRationales === "object"
              ? stored.feedback.optionRationales
              : {},
          masteryEvaluation: stored.feedback.masteryEvaluation ?? null,
          personalizedFeedback: stored.feedback.personalizedFeedback,
        }
      : null;

  return {
    quizSignature: stored.quizSignature,
    currentIndex: Number.isFinite(stored.currentIndex) ? Number(stored.currentIndex) : 0,
    topic: typeof stored.topic === "string" ? stored.topic : undefined,
    subjectId: typeof stored.subjectId === "string" ? normalizeStoredNotebookId(stored.subjectId) : undefined,
    selectedOption: isOptionKey(stored.selectedOption) ? stored.selectedOption : null,
    showHint: Boolean(stored.showHint),
    feedback,
    sessionId: typeof stored.sessionId === "string" ? stored.sessionId : "",
    notebookId: normalizeStoredNotebookId(stored.notebookId),
    isCompleted: Boolean(stored.isCompleted),
    completedAt: Number.isFinite(stored.completedAt) ? Number(stored.completedAt) : null,
    updatedAt: Number.isFinite(stored.updatedAt) ? Number(stored.updatedAt) : Date.now(),
  };
}

export function persistPracticeState(state: StoredPracticeState) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(
    PRACTICE_STATE_KEY,
    JSON.stringify({
      ...state,
      updatedAt: state.updatedAt || Date.now(),
    })
  );
}

export function clearStoredPracticeState() {
  if (!isBrowser()) {
    return;
  }

  removeStoreItem(PRACTICE_STATE_KEY);
}

export function loadStoredNotebookId(defaultId = DEFAULT_NOTEBOOK_ID) {
  if (!isBrowser()) {
    return defaultId;
  }

  return normalizeStoredNotebookId(
    readStoreItem(NOTEBOOK_KEY) ?? readStoreItem(LEGACY_SUBJECT_KEY),
    defaultId
  );
}

export function persistStoredNotebookId(notebookId: string) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(NOTEBOOK_KEY, normalizeStoredNotebookId(notebookId));
  const userId = getActiveUserId();
  const legacyKey = userId ? scopedKey(LEGACY_SUBJECT_KEY, userId) : LEGACY_SUBJECT_KEY;
  window.localStorage.removeItem(legacyKey);
}

// ============================================================
// Sessions & History
// ============================================================

export function loadStoredSessions(): ChatSession[] {
  if (!isBrowser()) {
    return [];
  }
  const stored = safeParse<Array<ChatSession & { subjectId?: string }>>(
    readStoreItem(SESSIONS_KEY),
    []
  );

  if (!Array.isArray(stored)) {
    return [];
  }

  return stored.map((session) => ({
    ...session,
    notebookId: normalizeStoredNotebookId(session.notebookId ?? session.subjectId),
  }));
}

export function saveStoredSession(session: ChatSession) {
  if (!isBrowser()) {
    return;
  }
  const sessions = loadStoredSessions();
  const index = sessions.findIndex((s) => s.id === session.id);
  if (index >= 0) {
    sessions[index] = session;
  } else {
    sessions.unshift(session);
  }
  
  // 按照更新时间倒序排列
  sessions.sort((a, b) => b.updatedAt - a.updatedAt);
  
  writeStoreItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function persistStoredSessions(sessions: ChatSession[]) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function deleteStoredSession(sessionId: string) {
  if (!isBrowser()) {
    return;
  }
  let sessions = loadStoredSessions();
  sessions = sessions.filter((s) => s.id !== sessionId);
  writeStoreItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function loadStoredModelConfig(): ModelConfig | null {
  if (!isBrowser()) {
    return null;
  }

  const stored = safeParse<ModelConfig | null>(
    readStoreItem(MODEL_CONFIG_KEY),
    null
  );

  if (
    !stored ||
    typeof stored !== "object" ||
    !Array.isArray(stored.available_models) ||
    typeof stored.current_model !== "string" ||
    typeof stored.embedding_model !== "string"
  ) {
    return null;
  }

  return normalizeModelConfig(stored);
}

export function persistStoredModelConfig(config: ModelConfig) {
  if (!isBrowser()) {
    return;
  }

  writeStoreItem(MODEL_CONFIG_KEY, JSON.stringify(normalizeModelConfig(config)));
}

export function setLearningStoreUser(userId: string | null) {
  if (!isBrowser()) {
    return;
  }

  if (userId && userId.trim()) {
    window.localStorage.setItem(ACTIVE_USER_KEY, userId.trim());
    return;
  }

  window.localStorage.removeItem(ACTIVE_USER_KEY);
}

export function clearLearningStore() {
  if (!isBrowser()) {
    return;
  }

  const activeUserId = getActiveUserId();
  removeStoreItem(MEMORY_KEY, activeUserId);
  removeStoreItem(QUIZ_KEY, activeUserId);
  removeStoreItem(PRACTICE_STATE_KEY, activeUserId);
  removeStoreItem(NOTEBOOK_KEY, activeUserId);
  removeStoreItem(LEGACY_SUBJECT_KEY, activeUserId);
  removeStoreItem(SESSIONS_KEY, activeUserId);
  removeStoreItem(MODEL_CONFIG_KEY, activeUserId);
  window.localStorage.removeItem(ACTIVE_USER_KEY);
}

/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first helper。
 */
export const loadStoredSubjectId = loadStoredNotebookId;
/**
 * @deprecated 兼容一轮迁移，新的前端代码应统一使用 notebook-first helper。
 */
export const persistStoredSubjectId = persistStoredNotebookId;

export type { ChatSession };
