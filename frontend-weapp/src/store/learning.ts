import Taro from "@tarojs/taro";
import { DEFAULT_NOTEBOOK_ID, type ChatMessage, type QuizItem } from "@/types/api";

const NOTEBOOK_KEY = "la_weapp_notebook_id";
const SESSION_KEY = "la_weapp_session_id";
const QUIZ_KEY = "la_weapp_latest_quiz";
const CHAT_DRAFT_KEY = "la_weapp_chat_draft";

export interface StoredQuizState {
  sessionId: string;
  subjectId: string;
  items: QuizItem[];
  currentIndex: number;
  answers: Record<string, string>;
}

export function getStoredNotebookId(): string {
  return Taro.getStorageSync(NOTEBOOK_KEY) || DEFAULT_NOTEBOOK_ID;
}

export function setStoredNotebookId(notebookId: string) {
  Taro.setStorageSync(NOTEBOOK_KEY, notebookId || DEFAULT_NOTEBOOK_ID);
}

export function getStoredSessionId(): string {
  return Taro.getStorageSync(SESSION_KEY) || "";
}

export function setStoredSessionId(sessionId: string) {
  Taro.setStorageSync(SESSION_KEY, sessionId);
}

export function clearStoredSessionId() {
  Taro.removeStorageSync(SESSION_KEY);
}

export function getStoredQuiz(): QuizItem[] {
  return getStoredQuizState().items;
}

export function getStoredQuizState(): StoredQuizState {
  const value = Taro.getStorageSync(QUIZ_KEY);
  if (Array.isArray(value)) {
    return {
      sessionId: "",
      subjectId: getStoredNotebookId(),
      items: value,
      currentIndex: 0,
      answers: {}
    };
  }
  if (value && typeof value === "object" && Array.isArray(value.items)) {
    return {
      sessionId: value.sessionId || "",
      subjectId: value.subjectId || getStoredNotebookId(),
      items: value.items,
      currentIndex: Number.isFinite(value.currentIndex) ? value.currentIndex : 0,
      answers: value.answers && typeof value.answers === "object" ? value.answers : {}
    };
  }
  return {
    sessionId: "",
    subjectId: getStoredNotebookId(),
    items: [],
    currentIndex: 0,
    answers: {}
  };
}

export function setStoredQuiz(items: QuizItem[], meta: Partial<Omit<StoredQuizState, "items">> = {}) {
  setStoredQuizState({
    sessionId: meta.sessionId || "",
    subjectId: meta.subjectId || getStoredNotebookId(),
    items,
    currentIndex: meta.currentIndex || 0,
    answers: meta.answers || {}
  });
}

export function setStoredQuizState(state: StoredQuizState) {
  Taro.setStorageSync(QUIZ_KEY, {
    sessionId: state.sessionId || "",
    subjectId: state.subjectId || getStoredNotebookId(),
    items: state.items,
    currentIndex: Math.max(0, state.currentIndex || 0),
    answers: state.answers || {}
  });
}

export function clearStoredQuiz() {
  Taro.removeStorageSync(QUIZ_KEY);
}

export function getChatDraft(): ChatMessage[] {
  return Taro.getStorageSync(CHAT_DRAFT_KEY) || [];
}

export function setChatDraft(messages: ChatMessage[]) {
  Taro.setStorageSync(CHAT_DRAFT_KEY, messages.slice(-40));
}

export function clearChatDraft() {
  Taro.removeStorageSync(CHAT_DRAFT_KEY);
}

export function createSessionId(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = (Math.random() * 16) | 0;
    const next = char === "x" ? value : (value & 0x3) | 0x8;
    return next.toString(16);
  });
}
