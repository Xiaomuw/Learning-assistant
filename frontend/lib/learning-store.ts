import type { Memory, ModelConfig, QuizItem, ChatSession } from "@/lib/api";

const MEMORY_KEY = "learning_memory";
const QUIZ_KEY = "learning_quiz";
const SUBJECT_KEY = "learning_subject_id";
const SESSIONS_KEY = "learning_chat_sessions";
const MODEL_CONFIG_KEY = "learning_model_config";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

function isBrowser() {
  return typeof window !== "undefined";
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

export function loadStoredMemory(): Memory {
  if (!isBrowser()) {
    return EMPTY_MEMORY;
  }

  const stored = safeParse<Partial<Memory>>(
    window.localStorage.getItem(MEMORY_KEY),
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

  window.localStorage.setItem(MEMORY_KEY, JSON.stringify(memory));
}

export function loadStoredQuiz(): QuizItem[] {
  if (!isBrowser()) {
    return [];
  }

  const stored = safeParse<QuizItem[]>(window.localStorage.getItem(QUIZ_KEY), []);
  return Array.isArray(stored) ? stored : [];
}

export function persistQuiz(quiz: QuizItem[]) {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.setItem(QUIZ_KEY, JSON.stringify(quiz));
}

export function clearStoredQuiz() {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.removeItem(QUIZ_KEY);
}

export function loadStoredSubjectId(defaultId = "general") {
  if (!isBrowser()) {
    return defaultId;
  }

  return window.localStorage.getItem(SUBJECT_KEY) ?? defaultId;
}

export function persistStoredSubjectId(subjectId: string) {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.setItem(SUBJECT_KEY, subjectId);
}

// ============================================================
// Sessions & History
// ============================================================

export function loadStoredSessions(): ChatSession[] {
  if (!isBrowser()) {
    return [];
  }
  const stored = safeParse<ChatSession[]>(window.localStorage.getItem(SESSIONS_KEY), []);
  return Array.isArray(stored) ? stored : [];
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
  
  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function persistStoredSessions(sessions: ChatSession[]) {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function deleteStoredSession(sessionId: string) {
  if (!isBrowser()) {
    return;
  }
  let sessions = loadStoredSessions();
  sessions = sessions.filter((s) => s.id !== sessionId);
  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function loadStoredModelConfig(): ModelConfig | null {
  if (!isBrowser()) {
    return null;
  }

  const stored = safeParse<ModelConfig | null>(
    window.localStorage.getItem(MODEL_CONFIG_KEY),
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

  return stored;
}

export function persistStoredModelConfig(config: ModelConfig) {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify(config));
}

export function clearLearningStore() {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.removeItem(MEMORY_KEY);
  window.localStorage.removeItem(QUIZ_KEY);
  window.localStorage.removeItem(SUBJECT_KEY);
  window.localStorage.removeItem(SESSIONS_KEY);
  window.localStorage.removeItem(MODEL_CONFIG_KEY);
}

export type { ChatSession };
