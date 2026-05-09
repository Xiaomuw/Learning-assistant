import { normalizeModelConfig } from "@/lib/api";
import type {
  ChatSession,
  MasteryEvaluationResult,
  Message,
  Memory,
  ModelConfig,
  Notebook,
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
const CHAT_DRAFTS_KEY = "learning_chat_drafts";
const ACTIVE_CHAT_SESSION_KEY = "learning_active_chat_session";
const LEGACY_SUBJECT_KEY = "learning_subject_id";
const NOTEBOOK_KEY = "learning_notebook_id";
const SESSIONS_KEY = "learning_chat_sessions";
const MODEL_CONFIG_KEY = "learning_model_config";
const ACTIVE_USER_KEY = "learning_active_user_id";
export const DEFAULT_NOTEBOOK_ID = "data-structure";
const CHAT_DRAFT_TTL_MS = 24 * 60 * 60 * 1000;
const LEGACY_DUPLICATE_QUALITY_GATE_TEXT = "发现重复题目";
const LEGACY_DUPLICATE_DRAFT_NOTICE =
  "这是旧质量门策略产生的历史失败结果；新请求会复用已有题，不应再因为题库已有相似题整包失败。";

export const FALLBACK_NOTEBOOKS: Notebook[] = [
  {
    id: "data-structure",
    name: "数据结构与算法",
    icon: "🌳",
    description: "线性表、树、图、排序、查找、动态规划、贪心等",
    doc_count: 0,
    created_at: "",
  },
  {
    id: "computer-network",
    name: "计算机网络",
    icon: "🌐",
    description: "TCP/IP、HTTP、DNS、路由协议、网络安全等",
    doc_count: 0,
    created_at: "",
  },
  {
    id: "computer-organization",
    name: "计算机组成原理",
    icon: "🧠",
    description: "数据表示、存储系统、指令系统、CPU、总线与 I/O 等",
    doc_count: 0,
    created_at: "",
  },
  {
    id: "operating-system",
    name: "操作系统原理",
    icon: "⚙️",
    description: "进程管理、内存管理、文件系统、I/O、死锁等",
    doc_count: 0,
    created_at: "",
  },
];

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

function isBrowser() {
  return typeof window !== "undefined";
}

function storageGetItem(key: string): string | null {
  if (!isBrowser()) {
    return null;
  }
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSetItem(key: string, value: string) {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Learning state is a convenience cache; pages should keep working without it.
  }
}

function storageRemoveItem(key: string) {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore restricted-storage failures.
  }
}

function getActiveUserId(): string | null {
  if (!isBrowser()) {
    return null;
  }

  const value = storageGetItem(ACTIVE_USER_KEY)?.trim();
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
    return storageGetItem(scopedKey(baseKey, userId));
  }

  return storageGetItem(baseKey);
}

function writeStoreItem(baseKey: string, value: string) {
  if (!isBrowser()) {
    return;
  }

  const userId = getActiveUserId();
  const key = userId ? scopedKey(baseKey, userId) : baseKey;
  storageSetItem(key, value);
}

function removeStoreItem(baseKey: string, userId?: string | null) {
  if (!isBrowser()) {
    return;
  }

  const activeUserId = userId ?? getActiveUserId();
  if (activeUserId) {
    storageRemoveItem(scopedKey(baseKey, activeUserId));
  }

  storageRemoveItem(baseKey);
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
  topics?: string[];
  subjectId?: string;
  subjectIds?: string[];
  sessionId?: string;
  sessionIds?: string[];
  quizSignature?: string;
  createdAt?: number;
  updatedAt?: number;
  shouldSwitchTopic?: boolean;
}

export interface StoredChatDraft {
  sessionId: string;
  notebookId: string;
  messages: Message[];
  updatedAt: number;
}

export interface StoredActiveChatSession {
  userId: string;
  sessionId: string;
  notebookId: string;
  updatedAt: number;
}

export function buildQuizSignature(quizList: QuizItem[]) {
  return quizList
    .map((item, index) => `${item.question_id || index}:${item.question}:${item.correct_option}`)
    .join("|");
}

function uniqueNonEmpty(values: Array<string | null | undefined>) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = value?.trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function compactQuizIdentityText(value: unknown) {
  return String(value ?? "").trim().toLowerCase().replace(/\s+/g, " ");
}

function quizItemIdentity(item: QuizItem) {
  const questionId = compactQuizIdentityText(item.question_id);
  if (questionId) {
    return `id:${questionId}`;
  }

  const optionText = Array.isArray(item.options)
    ? item.options.map((option) => compactQuizIdentityText(option.text)).join("|")
    : "";
  const question = compactQuizIdentityText(item.question);
  if (!question && !optionText) {
    return "";
  }
  return `sig:${question}|${optionText}|${compactQuizIdentityText(item.correct_option)}`;
}

export function getQuizItemNotebookId(
  item: QuizItem | null | undefined,
  fallbackId = DEFAULT_NOTEBOOK_ID
) {
  return normalizeStoredNotebookId(item?.notebook_id || item?.subject_id || fallbackId);
}

function quizItemWithContext(
  item: QuizItem,
  fallbackSubjectId?: string,
  sourceSessionId?: string
): QuizItem {
  const subjectId = getQuizItemNotebookId(item, fallbackSubjectId || DEFAULT_NOTEBOOK_ID);
  const itemSourceSessionId =
    typeof item.source_session_id === "string" ? item.source_session_id.trim() : "";
  const nextSourceSessionId = itemSourceSessionId || sourceSessionId?.trim() || "";
  return {
    ...item,
    subject_id: item.subject_id || subjectId,
    notebook_id: item.notebook_id || subjectId,
    ...(nextSourceSessionId ? { source_session_id: nextSourceSessionId } : {}),
  };
}

function quizItemWithOptionalContext(
  item: QuizItem,
  fallbackSubjectId?: string,
  sourceSessionId?: string
): QuizItem {
  if (
    !fallbackSubjectId &&
    !sourceSessionId &&
    !item.subject_id &&
    !item.notebook_id &&
    !item.source_session_id
  ) {
    return item;
  }
  return quizItemWithContext(item, fallbackSubjectId, sourceSessionId);
}

function mergeQuizLists(
  existingQuiz: QuizItem[],
  incomingQuiz: QuizItem[],
  existingSubjectId?: string,
  incomingSubjectId?: string,
  incomingSessionId?: string
) {
  const merged: QuizItem[] = [];
  const seen = new Set<string>();

  function appendItems(
    items: QuizItem[],
    fallbackSubjectId?: string,
    sourceSessionId?: string
  ) {
    for (const rawItem of items) {
      const item = quizItemWithContext(rawItem, fallbackSubjectId, sourceSessionId);
      const identity = quizItemIdentity(item);
      if (identity && seen.has(identity)) {
        continue;
      }
      if (identity) {
        seen.add(identity);
      }
      merged.push(item);
    }
  }

  appendItems(existingQuiz, existingSubjectId);
  appendItems(incomingQuiz, incomingSubjectId || existingSubjectId, incomingSessionId);
  return merged;
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
    topics: Array.isArray(stored.topics)
      ? uniqueNonEmpty(stored.topics.filter((topic): topic is string => typeof topic === "string"))
      : undefined,
    subjectId: typeof stored.subjectId === "string" ? normalizeStoredNotebookId(stored.subjectId) : undefined,
    subjectIds: Array.isArray(stored.subjectIds)
      ? uniqueNonEmpty(
          stored.subjectIds
            .filter((subjectId): subjectId is string => typeof subjectId === "string")
            .map((subjectId) => normalizeStoredNotebookId(subjectId))
        )
      : undefined,
    sessionId: typeof stored.sessionId === "string" ? stored.sessionId : undefined,
    sessionIds: Array.isArray(stored.sessionIds)
      ? uniqueNonEmpty(
          stored.sessionIds.filter(
            (sessionId): sessionId is string => typeof sessionId === "string"
          )
        )
      : undefined,
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

  const normalizedQuiz = quiz.map((item) =>
    quizItemWithOptionalContext(item, meta?.subjectId, meta?.sessionId)
  );
  writeStoreItem(QUIZ_KEY, JSON.stringify(normalizedQuiz));
  if (meta) {
    const now = Date.now();
    const topics = uniqueNonEmpty([
      ...(meta.topics || []),
      meta.topic,
      normalizedQuiz[0]?.knowledge_point,
    ]);
    const subjectIds = uniqueNonEmpty([
      ...(meta.subjectIds || []),
      meta.subjectId ? normalizeStoredNotebookId(meta.subjectId) : undefined,
      ...normalizedQuiz.map((item) => getQuizItemNotebookId(item)),
    ]);
    const sessionIds = uniqueNonEmpty([
      ...(meta.sessionIds || []),
      meta.sessionId,
      ...normalizedQuiz.map((item) => item.source_session_id),
    ]);
    writeStoreItem(
      QUIZ_META_KEY,
      JSON.stringify({
        ...meta,
        subjectId: normalizeStoredNotebookId(meta.subjectId),
        subjectIds,
        sessionIds,
        topic: meta.topic || topics[0],
        topics,
        quizSignature: meta.quizSignature || buildQuizSignature(normalizedQuiz),
        createdAt: meta.createdAt || now,
        updatedAt: now,
      })
    );
  } else {
    removeStoreItem(QUIZ_META_KEY);
  }
}

export function appendStoredQuiz(quiz: QuizItem[], meta?: StoredQuizMeta) {
  if (!isBrowser()) {
    return quiz;
  }

  const existingMeta = loadStoredQuizMeta();
  const existingQuiz = loadStoredQuiz();

  const incomingSubjectId = meta?.subjectId
    ? normalizeStoredNotebookId(meta.subjectId)
    : existingMeta?.subjectId || DEFAULT_NOTEBOOK_ID;
  const incomingSessionId = meta?.sessionId?.trim();
  const mergedQuiz = mergeQuizLists(
    existingQuiz,
    quiz,
    existingMeta?.subjectId,
    incomingSubjectId,
    incomingSessionId
  );
  const now = Date.now();
  const topics = uniqueNonEmpty([
    ...(existingMeta?.topics || []),
    existingMeta?.topic,
    ...(meta?.topics || []),
    meta?.topic,
    quiz[0]?.knowledge_point,
  ]);
  const subjectIds = uniqueNonEmpty([
    ...(existingMeta?.subjectIds || []),
    existingMeta?.subjectId,
    ...(meta?.subjectIds || []),
    incomingSubjectId,
    ...mergedQuiz.map((item) => getQuizItemNotebookId(item, incomingSubjectId)),
  ]);
  const sessionIds = uniqueNonEmpty([
    ...(existingMeta?.sessionIds || []),
    existingMeta?.sessionId,
    ...(meta?.sessionIds || []),
    incomingSessionId,
    ...mergedQuiz.map((item) => item.source_session_id),
  ]);
  const nextMeta: StoredQuizMeta = {
    ...existingMeta,
    ...meta,
    topic: topics.length > 1 ? "混合练习" : topics[0] || meta?.topic || existingMeta?.topic,
    topics,
    subjectId: incomingSubjectId,
    subjectIds,
    sessionIds,
    sessionId: meta?.sessionId || existingMeta?.sessionId,
    quizSignature: buildQuizSignature(mergedQuiz),
    createdAt: existingMeta?.createdAt || meta?.createdAt || now,
    updatedAt: now,
    shouldSwitchTopic: Boolean(meta?.shouldSwitchTopic),
  };

  writeStoreItem(QUIZ_KEY, JSON.stringify(mergedQuiz));
  writeStoreItem(QUIZ_META_KEY, JSON.stringify(nextMeta));
  return mergedQuiz;
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
  submittedOption?: "A" | "B" | "C" | "D";
  correctOption: "A" | "B" | "C" | "D";
  explanation: string;
  optionRationales: Record<string, string>;
  masteryEvaluation?: MasteryEvaluationResult | null;
  personalizedFeedback?: string;
}

export interface StoredPracticeState {
  quizSignature: string;
  quizItemCount?: number;
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
          submittedOption: isOptionKey(stored.feedback.submittedOption)
            ? stored.feedback.submittedOption
            : undefined,
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
    quizItemCount: Number.isFinite(stored.quizItemCount) ? Number(stored.quizItemCount) : undefined,
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
  storageRemoveItem(legacyKey);
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

function draftTitle(messages: Message[]) {
  const firstUserMessage = messages.find((message) => message.role === "user");
  return (firstUserMessage?.content || "未完成对话").slice(0, 50);
}

function isLegacyDuplicateQualityGateMessage(message: Message) {
  return (
    message.role === "assistant" &&
    message.content.includes(LEGACY_DUPLICATE_QUALITY_GATE_TEXT)
  );
}

function annotateLegacyDuplicateQualityGateMessage(message: Message): Message {
  if (
    !isLegacyDuplicateQualityGateMessage(message) ||
    message.content.includes(LEGACY_DUPLICATE_DRAFT_NOTICE)
  ) {
    return message;
  }

  return {
    ...message,
    content: `${message.content}\n\n${LEGACY_DUPLICATE_DRAFT_NOTICE}`,
  };
}

function normalizeDraft(value: unknown): StoredChatDraft | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const draft = value as Partial<StoredChatDraft>;
  const sessionId = typeof draft.sessionId === "string" ? draft.sessionId.trim() : "";
  const messages = Array.isArray(draft.messages)
    ? draft.messages.filter(
        (message): message is Message =>
          Boolean(message) &&
          typeof message === "object" &&
          (message.role === "user" || message.role === "assistant") &&
          typeof message.content === "string"
      ).map(annotateLegacyDuplicateQualityGateMessage)
    : [];
  const updatedAt = Number(draft.updatedAt);

  if (!sessionId || messages.length === 0 || !Number.isFinite(updatedAt)) {
    return null;
  }

  if (Date.now() - updatedAt > CHAT_DRAFT_TTL_MS) {
    return null;
  }

  return {
    sessionId,
    notebookId: normalizeStoredNotebookId(draft.notebookId),
    messages,
    updatedAt,
  };
}

function isLegacyDuplicateDraft(draft: StoredChatDraft) {
  return draft.messages.some(isLegacyDuplicateQualityGateMessage);
}

function loadStoredChatDraftMap(): Record<string, StoredChatDraft> {
  if (!isBrowser()) {
    return {};
  }

  const stored = safeParse<Record<string, unknown>>(readStoreItem(CHAT_DRAFTS_KEY), {});
  const drafts: Record<string, StoredChatDraft> = {};

  for (const [sessionId, rawDraft] of Object.entries(stored || {})) {
    const draft = normalizeDraft(rawDraft);
    if (draft) {
      drafts[sessionId] = draft;
    }
  }

  return drafts;
}

function persistStoredChatDraftMap(drafts: Record<string, StoredChatDraft>) {
  writeStoreItem(CHAT_DRAFTS_KEY, JSON.stringify(drafts));
}

export function persistStoredChatDraft(draft: StoredChatDraft) {
  if (!isBrowser()) {
    return;
  }

  const draftSessionId =
    typeof draft.sessionId === "string" ? draft.sessionId.trim() : "";
  const draftMessages = Array.isArray(draft.messages) ? draft.messages : [];
  if (draftSessionId && draftMessages.length === 0) {
    clearStoredChatDraft(draftSessionId);
    return;
  }

  const normalized = normalizeDraft({
    ...draft,
    notebookId: normalizeStoredNotebookId(draft.notebookId),
    updatedAt: draft.updatedAt || Date.now(),
  });
  if (!normalized) {
    return;
  }

  const drafts = loadStoredChatDraftMap();
  drafts[normalized.sessionId] = normalized;
  persistStoredChatDraftMap(drafts);
}

export function loadStoredChatDraft(sessionId: string): StoredChatDraft | null {
  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) {
    return null;
  }

  return loadStoredChatDraftMap()[normalizedSessionId] ?? null;
}

export function loadLatestStoredChatDraft(): StoredChatDraft | null {
  const drafts = Object.values(loadStoredChatDraftMap()).sort(
    (a, b) => b.updatedAt - a.updatedAt
  );
  return drafts[0] ?? null;
}

function normalizeActiveChatSession(
  rawSession: unknown,
  expectedUserId?: string
): StoredActiveChatSession | null {
  if (!rawSession || typeof rawSession !== "object") {
    return null;
  }

  const session = rawSession as Partial<StoredActiveChatSession>;
  const userId = typeof session.userId === "string" ? session.userId.trim() : "";
  const sessionId =
    typeof session.sessionId === "string" ? session.sessionId.trim() : "";
  const notebookId =
    typeof session.notebookId === "string"
      ? normalizeStoredNotebookId(session.notebookId)
      : DEFAULT_NOTEBOOK_ID;
  const updatedAt = Number(session.updatedAt);

  if (!userId || !sessionId || !Number.isFinite(updatedAt)) {
    return null;
  }

  if (expectedUserId && userId !== expectedUserId) {
    return null;
  }

  return {
    userId,
    sessionId,
    notebookId,
    updatedAt,
  };
}

export function persistStoredActiveChatSession(
  session: StoredActiveChatSession
) {
  if (!isBrowser()) {
    return;
  }

  const normalized = normalizeActiveChatSession({
    ...session,
    notebookId: normalizeStoredNotebookId(session.notebookId),
    updatedAt: session.updatedAt || Date.now(),
  });
  if (!normalized) {
    return;
  }

  writeStoreItem(ACTIVE_CHAT_SESSION_KEY, JSON.stringify(normalized));
}

export function loadStoredActiveChatSession(
  userId?: string
): StoredActiveChatSession | null {
  if (!isBrowser()) {
    return null;
  }

  const stored = safeParse<Partial<StoredActiveChatSession> | null>(
    readStoreItem(ACTIVE_CHAT_SESSION_KEY),
    null
  );
  return normalizeActiveChatSession(stored, userId);
}

export function clearStoredActiveChatSession(userId?: string) {
  if (!isBrowser()) {
    return;
  }

  const existing = loadStoredActiveChatSession();
  if (userId && existing && existing.userId !== userId) {
    return;
  }

  removeStoreItem(ACTIVE_CHAT_SESSION_KEY, userId);
}

export function clearStoredChatDraft(sessionId: string) {
  if (!isBrowser()) {
    return;
  }

  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) {
    return;
  }

  const drafts = loadStoredChatDraftMap();
  delete drafts[normalizedSessionId];
  persistStoredChatDraftMap(drafts);
}

export function mergeStoredChatDraftsWithSessions(sessions: ChatSession[]): ChatSession[] {
  const drafts = Object.values(loadStoredChatDraftMap());
  if (drafts.length === 0) {
    return sessions;
  }

  const byId = new Map<string, ChatSession>();
  for (const session of sessions) {
    byId.set(session.id, session);
  }

  for (const draft of drafts) {
    const existing = byId.get(draft.sessionId);
    if (!existing) {
      byId.set(draft.sessionId, {
        id: draft.sessionId,
        title: draftTitle(draft.messages),
        notebookId: draft.notebookId,
        updatedAt: draft.updatedAt,
        messages: draft.messages,
        latestQuiz: [],
      });
      continue;
    }

    if (
      isLegacyDuplicateDraft(draft) &&
      existing.updatedAt >= draft.updatedAt
    ) {
      continue;
    }

    if (
      draft.updatedAt >= existing.updatedAt ||
      draft.messages.length >= existing.messages.length
    ) {
      byId.set(draft.sessionId, {
        ...existing,
        notebookId: existing.notebookId || draft.notebookId,
        updatedAt: Math.max(existing.updatedAt, draft.updatedAt),
        messages: draft.messages,
      });
    }
  }

  return Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt);
}

export function deleteStoredSession(sessionId: string) {
  if (!isBrowser()) {
    return;
  }
  let sessions = loadStoredSessions();
  sessions = sessions.filter((s) => s.id !== sessionId);
  writeStoreItem(SESSIONS_KEY, JSON.stringify(sessions));

  const activeSession = loadStoredActiveChatSession();
  if (activeSession?.sessionId === sessionId) {
    clearStoredActiveChatSession(activeSession.userId);
  }
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
    storageSetItem(ACTIVE_USER_KEY, userId.trim());
    return;
  }

  storageRemoveItem(ACTIVE_USER_KEY);
}

export function clearLearningStore() {
  if (!isBrowser()) {
    return;
  }

  const activeUserId = getActiveUserId();
  removeStoreItem(MEMORY_KEY, activeUserId);
  removeStoreItem(QUIZ_KEY, activeUserId);
  removeStoreItem(PRACTICE_STATE_KEY, activeUserId);
  removeStoreItem(CHAT_DRAFTS_KEY, activeUserId);
  removeStoreItem(NOTEBOOK_KEY, activeUserId);
  removeStoreItem(LEGACY_SUBJECT_KEY, activeUserId);
  removeStoreItem(SESSIONS_KEY, activeUserId);
  removeStoreItem(MODEL_CONFIG_KEY, activeUserId);
  storageRemoveItem(ACTIVE_USER_KEY);
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
