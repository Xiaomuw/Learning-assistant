import Taro from "@tarojs/taro";
import {
  DEFAULT_NOTEBOOK_ID,
  type ChatMessage,
  type LearningCenterPracticeTarget,
  type Memory,
  type PracticeAttemptResult,
  type QuizItem
} from "@/types/api";

const NOTEBOOK_KEY = "la_weapp_notebook_id";
const SESSION_KEY = "la_weapp_session_id";
const QUIZ_KEY = "la_weapp_latest_quiz";
const CHAT_DRAFT_KEY = "la_weapp_chat_draft";
const MEMORY_KEY = "la_weapp_memory";
const LEARNING_CENTER_TARGET_KEY = "la_weapp_learning_center_target";
const ACTIVE_USER_KEY = "la_weapp_active_user_id";
const AUTH_USER_KEY = "la_weapp_user";

export interface StoredQuizState {
  sessionId: string;
  subjectId: string;
  items: QuizItem[];
  currentIndex: number;
  answers: Record<string, string>;
  feedback?: PracticeAttemptResult | null;
  feedbackQuizKey?: string;
  feedbacks?: Record<string, PracticeAttemptResult>;
  isCompleted?: boolean;
  completedAt?: number | null;
}

export interface AppendStoredQuizResult {
  state: StoredQuizState;
  addedCount: number;
  totalCount: number;
  startIndex: number;
}

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: ""
};

function hasStoredValue(value: any) {
  return value !== undefined && value !== null && value !== "";
}

function scopedKey(baseKey: string, userId: string) {
  return `${baseKey}:${userId}`;
}

function normalizeNotebookId(notebookId: string | null | undefined) {
  const normalized = notebookId?.trim();
  return normalized && normalized !== "general" ? normalized : DEFAULT_NOTEBOOK_ID;
}

function quizIdentity(item: QuizItem) {
  const id = item.question_id?.trim();
  if (id) return `id:${id}`;
  return `${item.question || ""}|${(item.options || []).map((option) => option.text).join("|")}|${item.correct_option || ""}`.toLowerCase();
}

function appendUniqueQuizItems(current: QuizItem[], incoming: QuizItem[]) {
  const seen = new Set<string>();
  const merged: QuizItem[] = [];
  let addedCount = 0;

  current.forEach((item) => {
    const identity = quizIdentity(item);
    if (identity) seen.add(identity);
    merged.push(item);
  });

  incoming.forEach((item) => {
    const identity = quizIdentity(item);
    if (identity && seen.has(identity)) return;
    if (identity) seen.add(identity);
    merged.push(item);
    addedCount += 1;
  });

  return { merged, addedCount };
}

function normalizeFeedbacks(value: any): Record<string, PracticeAttemptResult> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.entries(value).reduce<Record<string, PracticeAttemptResult>>((result, [key, feedback]) => {
    if (key && feedback && typeof feedback === "object" && !Array.isArray(feedback)) {
      result[key] = feedback as PracticeAttemptResult;
    }
    return result;
  }, {});
}

function mergeCurrentFeedback(
  feedbacks: Record<string, PracticeAttemptResult>,
  feedback: PracticeAttemptResult | null | undefined,
  feedbackQuizKey: string | undefined
) {
  if (!feedback || !feedbackQuizKey) {
    return feedbacks;
  }
  return {
    ...feedbacks,
    [feedbackQuizKey]: feedback
  };
}

function getUserIdFromAuthStorage() {
  const user = Taro.getStorageSync(AUTH_USER_KEY);
  return typeof user?.id === "string" && user.id.trim() ? user.id.trim() : "";
}

export function getLearningStoreUser(): string {
  const explicitUserId = Taro.getStorageSync(ACTIVE_USER_KEY);
  if (typeof explicitUserId === "string" && explicitUserId.trim()) {
    return explicitUserId.trim();
  }
  const authUserId = getUserIdFromAuthStorage();
  if (authUserId) {
    Taro.setStorageSync(ACTIVE_USER_KEY, authUserId);
  }
  return authUserId;
}

export function setLearningStoreUser(userId: string | null | undefined) {
  const normalized = userId?.trim();
  if (normalized) {
    Taro.setStorageSync(ACTIVE_USER_KEY, normalized);
  } else {
    Taro.removeStorageSync(ACTIVE_USER_KEY);
  }
}

function readStoreValue(baseKey: string) {
  const userId = getLearningStoreUser();
  if (!userId) {
    return Taro.getStorageSync(baseKey);
  }

  const userKey = scopedKey(baseKey, userId);
  const scopedValue = Taro.getStorageSync(userKey);
  if (hasStoredValue(scopedValue)) {
    return scopedValue;
  }

  const legacyValue = Taro.getStorageSync(baseKey);
  if (hasStoredValue(legacyValue)) {
    Taro.setStorageSync(userKey, legacyValue);
    Taro.removeStorageSync(baseKey);
    return legacyValue;
  }

  return "";
}

function writeStoreValue(baseKey: string, value: any) {
  const userId = getLearningStoreUser();
  Taro.setStorageSync(userId ? scopedKey(baseKey, userId) : baseKey, value);
}

function removeStoreValue(baseKey: string, userId?: string | null) {
  const targetUserId = userId ?? getLearningStoreUser();
  if (targetUserId) {
    Taro.removeStorageSync(scopedKey(baseKey, targetUserId));
  }
  Taro.removeStorageSync(baseKey);
}

export function getStoredNotebookId(): string {
  return normalizeNotebookId(readStoreValue(NOTEBOOK_KEY));
}

export function setStoredNotebookId(notebookId: string) {
  writeStoreValue(NOTEBOOK_KEY, normalizeNotebookId(notebookId));
}

export function getStoredSessionId(): string {
  return readStoreValue(SESSION_KEY) || "";
}

export function setStoredSessionId(sessionId: string) {
  writeStoreValue(SESSION_KEY, sessionId);
}

export function clearStoredSessionId(userId?: string | null) {
  removeStoreValue(SESSION_KEY, userId);
}

export function getStoredQuiz(): QuizItem[] {
  return getStoredQuizState().items;
}

export function getStoredQuizState(): StoredQuizState {
  const value = readStoreValue(QUIZ_KEY);
  if (Array.isArray(value)) {
    return {
      sessionId: "",
      subjectId: getStoredNotebookId(),
      items: value,
      currentIndex: 0,
      answers: {},
      feedback: null,
      feedbackQuizKey: "",
      feedbacks: {},
      isCompleted: false,
      completedAt: null
    };
  }
  if (value && typeof value === "object" && Array.isArray(value.items)) {
    const feedback = value.feedback && typeof value.feedback === "object" ? value.feedback as PracticeAttemptResult : null;
    const feedbackQuizKey = typeof value.feedbackQuizKey === "string" ? value.feedbackQuizKey : "";
    const feedbacks = mergeCurrentFeedback(normalizeFeedbacks(value.feedbacks), feedback, feedbackQuizKey);
    return {
      sessionId: value.sessionId || "",
      subjectId: normalizeNotebookId(value.subjectId || getStoredNotebookId()),
      items: value.items,
      currentIndex: Number.isFinite(value.currentIndex) ? value.currentIndex : 0,
      answers: value.answers && typeof value.answers === "object" ? value.answers : {},
      feedback,
      feedbackQuizKey,
      feedbacks,
      isCompleted: Boolean(value.isCompleted),
      completedAt: Number.isFinite(value.completedAt) ? Number(value.completedAt) : null
    };
  }
  return {
    sessionId: "",
    subjectId: getStoredNotebookId(),
    items: [],
    currentIndex: 0,
    answers: {},
    feedback: null,
    feedbackQuizKey: "",
    feedbacks: {},
    isCompleted: false,
    completedAt: null
  };
}

export function setStoredQuiz(items: QuizItem[], meta: Partial<Omit<StoredQuizState, "items">> = {}) {
  setStoredQuizState({
    sessionId: meta.sessionId || "",
    subjectId: normalizeNotebookId(meta.subjectId || getStoredNotebookId()),
    items,
    currentIndex: meta.currentIndex ?? 0,
    answers: meta.answers || {},
    feedback: meta.feedback ?? null,
    feedbackQuizKey: meta.feedbackQuizKey || "",
    feedbacks: meta.feedbacks || {},
    isCompleted: Boolean(meta.isCompleted),
    completedAt: meta.completedAt ?? null
  });
}

export function appendStoredQuiz(items: QuizItem[], meta: Partial<Omit<StoredQuizState, "items">> = {}): AppendStoredQuizResult {
  const current = getStoredQuizState();
  const startIndex = current.items.length;
  const { merged, addedCount } = appendUniqueQuizItems(current.items, items);
  const shouldJumpToNewItems = addedCount > 0 && (current.items.length === 0 || current.isCompleted);
  const nextState: StoredQuizState = {
    sessionId: meta.sessionId || current.sessionId || "",
    subjectId: normalizeNotebookId(meta.subjectId || current.subjectId || getStoredNotebookId()),
    items: merged,
    currentIndex: shouldJumpToNewItems
      ? startIndex
      : Math.min(current.currentIndex || 0, Math.max(merged.length - 1, 0)),
    answers: current.answers || {},
    feedback: shouldJumpToNewItems ? null : current.feedback ?? null,
    feedbackQuizKey: shouldJumpToNewItems ? "" : current.feedbackQuizKey || "",
    feedbacks: current.feedbacks || {},
    isCompleted: shouldJumpToNewItems ? false : Boolean(current.isCompleted),
    completedAt: shouldJumpToNewItems ? null : current.completedAt ?? null
  };
  setStoredQuizState(nextState);
  return {
    state: nextState,
    addedCount,
    totalCount: merged.length,
    startIndex
  };
}

export function setStoredQuizState(state: StoredQuizState) {
  const feedbacks = mergeCurrentFeedback(state.feedbacks || {}, state.feedback, state.feedbackQuizKey);
  writeStoreValue(QUIZ_KEY, {
    sessionId: state.sessionId || "",
    subjectId: normalizeNotebookId(state.subjectId || getStoredNotebookId()),
    items: state.items,
    currentIndex: Math.max(0, state.currentIndex || 0),
    answers: state.answers || {},
    feedback: state.feedback ?? null,
    feedbackQuizKey: state.feedbackQuizKey || "",
    feedbacks,
    isCompleted: Boolean(state.isCompleted),
    completedAt: state.completedAt ?? null
  });
}

export function clearStoredQuiz(userId?: string | null) {
  removeStoreValue(QUIZ_KEY, userId);
}

export function getChatDraft(): ChatMessage[] {
  const value = readStoreValue(CHAT_DRAFT_KEY);
  return Array.isArray(value) ? value : [];
}

export function setChatDraft(messages: ChatMessage[]) {
  writeStoreValue(CHAT_DRAFT_KEY, messages.slice(-40));
}

export function clearChatDraft(userId?: string | null) {
  removeStoreValue(CHAT_DRAFT_KEY, userId);
}

export function getStoredMemory(): Memory {
  const value = readStoreValue(MEMORY_KEY);
  if (!value || typeof value !== "object") {
    return EMPTY_MEMORY;
  }
  return {
    weak_points: Array.isArray(value.weak_points) ? value.weak_points : [],
    error_count: value.error_count && typeof value.error_count === "object" ? value.error_count : {},
    recent_topics: Array.isArray(value.recent_topics) ? value.recent_topics : [],
    last_session: value.last_session || ""
  };
}

export function setStoredMemory(memory: Memory) {
  writeStoreValue(MEMORY_KEY, memory || EMPTY_MEMORY);
}

export function getLearningCenterTarget(): LearningCenterPracticeTarget | null {
  const value = readStoreValue(LEARNING_CENTER_TARGET_KEY);
  if (!value || typeof value !== "object" || !value.conceptId || !value.conceptName) {
    return null;
  }
  return {
    subjectId: normalizeNotebookId(value.subjectId),
    subjectName: value.subjectName || "",
    chapterId: value.chapterId || "",
    chapterName: value.chapterName || "",
    topicId: value.topicId || "",
    topicName: value.topicName || "",
    conceptId: value.conceptId,
    conceptName: value.conceptName,
    reason: value.reason || ""
  };
}

export function setLearningCenterTarget(target: LearningCenterPracticeTarget) {
  writeStoreValue(LEARNING_CENTER_TARGET_KEY, {
    ...target,
    subjectId: normalizeNotebookId(target.subjectId)
  });
}

export function clearLearningCenterTarget(userId?: string | null) {
  removeStoreValue(LEARNING_CENTER_TARGET_KEY, userId);
}

export function clearLearningDataForUser(userId?: string | null) {
  const targetUserId = userId ?? getLearningStoreUser();
  clearStoredSessionId(targetUserId);
  clearStoredQuiz(targetUserId);
  clearChatDraft(targetUserId);
  clearLearningCenterTarget(targetUserId);
  removeStoreValue(MEMORY_KEY, targetUserId);
  removeStoreValue(NOTEBOOK_KEY, targetUserId);
}

export function createSessionId(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = (Math.random() * 16) | 0;
    const next = char === "x" ? value : (value & 0x3) | 0x8;
    return next.toString(16);
  });
}
