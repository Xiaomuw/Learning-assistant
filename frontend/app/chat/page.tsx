"use client";

import { useEffect, useRef, useState } from "react";
import { Clock, Sparkles } from "lucide-react";
import ChatWindow from "@/components/ChatWindow";
import InputBar from "@/components/InputBar";
import NotebookSelector from "@/components/NotebookSelector";
import BottomNav from "@/components/BottomNav";
import { useAuth } from "@/components/AuthProvider";
import HistoryDrawer from "@/components/HistoryDrawer";
import SessionSummaryCard, {
  hasSessionSummary,
} from "@/components/SessionSummaryCard";
import {
  deleteSession as deleteSessionRemote,
  fetchNotebookKnowledgeStatus,
  fetchModelConfig,
  fetchNotebooks,
  fetchSessions,
  fetchUserMemory,
  normalizeExplanationPayload,
  normalizeMemoryPayload,
  sendChatSSE,
  uploadPDFToNotebook,
  type Memory,
  type Message,
  type MessageProcess,
  type MessageProcessExecution,
  type MessageProcessStage,
  type MessageProcessToolCall,
  type ModelConfig,
  type Notebook,
  type NotebookKnowledgeStatus,
  type QuizClarificationPanel,
  type QuizItem,
  type QuizRequestResolution,
} from "@/lib/api";
import {
  DEFAULT_NOTEBOOK_ID,
  FALLBACK_NOTEBOOKS,
  clearStoredChatDraft,
  clearStoredPracticeState,
  loadLatestStoredChatDraft,
  loadStoredChatDraft,
  loadStoredMemory,
  loadStoredModelConfig,
  loadStoredNotebookId,
  loadStoredSessions,
  mergeStoredChatDraftsWithSessions,
  persistMemory,
  persistQuiz,
  persistStoredChatDraft,
  persistStoredModelConfig,
  persistStoredSessions,
  persistStoredNotebookId,
  type ChatSession,
} from "@/lib/learning-store";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: "",
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  concept: "概念理解",
  problem: "解题辅导",
  compare: "概念比较",
  application: "应用场景",
  practice: "练习出题",
  review: "复习巩固",
  meta: "助手信息",
  smalltalk: "寒暄对话",
  mcq_problem: "选择题判题",
};

const EXECUTION_MODE_LABELS: Record<string, string> = {
  direct_answer: "直接回答",
  tool_calling: "工具调用",
  structured_output: "结构化回答",
  deterministic_context: "确定性检索讲解",
};

const ROUTE_LABELS: Record<string, string> = {
  fast: "快速回答",
  explain: "教学讲解",
  rag: "资料优先",
  agent: "工具增强",
  practice: "练习出题",
};

const NOTEBOOK_POLICY_LABELS: Record<string, string> = {
  skip: "不查 notebook",
  optional: "资料可选",
  required: "优先参考资料",
  strict: "只按资料",
};

const SEARCH_POLICY_LABELS: Record<string, string> = {
  forbidden: "不搜索",
  allowed: "可搜索",
  required: "必须搜索",
};

const TOOL_LABELS: Record<string, string> = {
  search_notebook_context: "搜索笔记本",
  get_session_summary: "读取会话摘要",
  get_user_learning_profile: "读取学习画像",
  recommend_questions: "推荐练习题",
  mcp_web_search: "网页搜索(MCP)",
  mcp_web_read: "网页读取(MCP)",
  tavily_web_search: "网络搜索(Tavily)",
};

const PROCESS_STAGE_ORDER: Record<string, number> = {
  status: 0,
  heartbeat: 0.5,
  routing: 1,
  guard: 2,
  retrieval: 3,
  context_audit: 4,
  web_search: 5,
  teaching: 6,
  tool_decision: 7,
  execution: 8,
  answer: 9,
  error: 10,
};

const COVERAGE_LABELS: Record<NotebookKnowledgeStatus["coverage_level"], string> = {
  empty: "知识库为空",
  sparse: "资料较少",
  partial: "资料部分可用",
  ready: "知识库可用",
};

function createInitialProcess(message = "已连接学习引擎，正在准备处理。"): MessageProcess {
  return {
    currentStage: "准备中",
    stages: [
      {
        key: "status",
        label: "准备中",
        status: "running",
        detail: message,
      },
    ],
    reasoningSummary: "",
    toolCalls: [],
  };
}

function buildChatFailurePresentation(
  rawMessage: string,
  reason?: string,
  retryable = true
): { label: string; message: string } {
  if (reason === "timeout" || rawMessage.includes("处理超时")) {
    return {
      label: "处理超时",
      message:
        rawMessage ||
        "处理超时：学习引擎处理时间较长，本轮请求已经中断。你可以稍后重试，或换一种更具体的问法。",
    };
  }

  if (reason === "model_unavailable") {
    return {
      label: "模型暂不可用",
      message:
        rawMessage ||
        "模型服务暂时不可用，请稍后再试。当前页面和历史记录仍可继续使用。",
    };
  }

  if (reason === "stream_interrupted" || reason === "stream_cancelled") {
    return {
      label: "连接中断",
      message:
        rawMessage ||
        "连接已中断：当前回答没有完整返回，你可以直接手动重试。",
    };
  }

  return {
    label: retryable ? "可重试失败" : "处理失败",
    message:
      rawMessage ||
      (retryable
        ? "学习引擎处理失败，你可以直接再发一次问题。"
        : "学习引擎处理失败，请稍后再试。"),
  };
}

function cloneProcess(process?: MessageProcess): MessageProcess {
  if (!process) {
    return createInitialProcess();
  }

  return {
    currentStage: process.currentStage,
    stages: process.stages.map((stage) => ({ ...stage })),
    reasoningSummary: process.reasoningSummary ?? "",
    execution: process.execution ? { ...process.execution } : undefined,
    toolCalls: (process.toolCalls ?? []).map((toolCall) => ({ ...toolCall })),
  };
}

function finalizeRunningStages(
  stages: MessageProcessStage[]
): MessageProcessStage[] {
  return stages.map((stage) =>
    stage.status === "running"
      ? ({ ...stage, status: "completed" } as MessageProcessStage)
      : stage
  );
}

function upsertProcessStage(
  process: MessageProcess | undefined,
  stage: MessageProcessStage,
  currentStage: string,
  options: { completeRunning?: boolean } = {}
): MessageProcess {
  const nextProcess = cloneProcess(process);
  const completeRunning = options.completeRunning ?? true;
  const stages: MessageProcessStage[] = completeRunning
    ? finalizeRunningStages(nextProcess.stages)
    : nextProcess.stages.map((item): MessageProcessStage => ({ ...item }));
  const nextStage: MessageProcessStage = { ...stage };
  const existingIndex = stages.findIndex((item) => item.key === nextStage.key);

  if (existingIndex >= 0) {
    stages[existingIndex] = nextStage;
  } else {
    stages.push(nextStage);
  }

  stages.sort(
    (left, right) =>
      (PROCESS_STAGE_ORDER[left.key] ?? 99) - (PROCESS_STAGE_ORDER[right.key] ?? 99)
  );

  nextProcess.currentStage = currentStage;
  nextProcess.stages = stages;
  return nextProcess;
}

function stringifyProcessArg(value: unknown) {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (value == null) {
    return "";
  }
  return String(value).trim();
}

function summarizeToolArgs(name: string, args: unknown): string {
  if (!args || typeof args !== "object" || Array.isArray(args)) {
    return "无额外参数";
  }

  const payload = args as Record<string, unknown>;
  const parts: string[] = [];

  if (name === "search_notebook_context") {
    const query = stringifyProcessArg(payload.query);
    const topK = stringifyProcessArg(payload.top_k);
    if (query) {
      parts.push(`query=${query}`);
    }
    if (topK) {
      parts.push(`top_k=${topK}`);
    }
  } else if (name === "get_session_summary") {
    const includeOpenLoops = stringifyProcessArg(payload.include_open_loops);
    if (includeOpenLoops) {
      parts.push(`包含未解决点=${includeOpenLoops}`);
    }
  } else if (name === "get_user_learning_profile") {
    const focus = stringifyProcessArg(payload.focus);
    if (focus) {
      parts.push(`focus=${focus}`);
    }
  } else if (name === "recommend_questions") {
    const topic = stringifyProcessArg(payload.topic);
    const limit = stringifyProcessArg(payload.limit);
    if (topic) {
      parts.push(`topic=${topic}`);
    }
    if (limit) {
      parts.push(`limit=${limit}`);
    }
  } else if (name === "mcp_web_search") {
    const query = stringifyProcessArg(payload.query);
    const maxResults = stringifyProcessArg(payload.max_results);
    if (query) {
      parts.push(`query=${query}`);
    }
    if (maxResults) {
      parts.push(`max_results=${maxResults}`);
    }
  } else if (name === "mcp_web_read") {
    const url = stringifyProcessArg(payload.url);
    if (url) {
      parts.push(`url=${url}`);
    }
  } else if (name === "tavily_web_search") {
    const query = stringifyProcessArg(payload.query);
    const maxResults = stringifyProcessArg(payload.max_results);
    if (query) {
      parts.push(`query=${query}`);
    }
    if (maxResults) {
      parts.push(`max_results=${maxResults}`);
    }
  } else {
    Object.entries(payload)
      .slice(0, 3)
      .forEach(([key, value]) => {
        const normalized = stringifyProcessArg(value);
        if (normalized) {
          parts.push(`${key}=${normalized}`);
        }
      });
  }

  return parts.length > 0 ? parts.join(" · ") : "无额外参数";
}

function normalizeToolCalls(rawToolCalls: unknown): MessageProcessToolCall[] {
  if (!Array.isArray(rawToolCalls)) {
    return [];
  }

  return rawToolCalls.reduce<MessageProcessToolCall[]>((accumulator, item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return accumulator;
      }

      const payload = item as Record<string, unknown>;
      const name = String(payload.name ?? "").trim();
      const error =
        typeof payload.error === "string" && payload.error.trim()
          ? payload.error.trim()
          : undefined;
      const docCount =
        typeof payload.doc_count === "number" && Number.isFinite(payload.doc_count)
          ? payload.doc_count
          : undefined;

      accumulator.push({
        name,
        label: TOOL_LABELS[name] ?? (name || "未知工具"),
        success: Boolean(payload.success),
        argsSummary: summarizeToolArgs(name, payload.args),
        error,
        docCount,
      });

      return accumulator;
    }, []);
}

function mergeToolCalls(
  primary: unknown,
  external: unknown
): MessageProcessToolCall[] {
  const merged = [...normalizeToolCalls(primary), ...normalizeToolCalls(external)];
  const seen = new Set<string>();
  return merged.filter((toolCall, index) => {
    const key = `${toolCall.name}:${toolCall.argsSummary}:${toolCall.success}:${toolCall.error ?? ""}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return index >= 0;
  });
}

function mergeProcessToolCalls(
  existing: MessageProcessToolCall[] | undefined,
  incoming: MessageProcessToolCall[]
): MessageProcessToolCall[] {
  const seen = new Set<string>();
  const merged = [...(existing ?? []), ...incoming];
  return merged.filter((toolCall) => {
    const key = `${toolCall.name}:${toolCall.argsSummary}:${toolCall.success}:${toolCall.error ?? ""}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function hasRetrievalStatusPayload(data: Record<string, unknown>) {
  return (
    "retrieval_diagnosis" in data ||
    "rag_ready" in data ||
    "doc_count" in data ||
    "web_search_required" in data ||
    "rag_warning" in data
  );
}

function hasContextAuditStatusPayload(data: Record<string, unknown>) {
  return (
    "context_audit" in data ||
    "verified_context" in data ||
    "verified_count" in data
  );
}

function hasWebSearchStatusPayload(data: Record<string, unknown>) {
  return (
    "web_search_diagnosis" in data ||
    "web_search_attempted" in data ||
    "web_search_used" in data ||
    "web_search_error" in data ||
    "external_tool_calls" in data
  );
}

function hasTeachingStatusPayload(data: Record<string, unknown>) {
  return (
    "teaching_input_type" in data ||
    "teaching_user_state" in data ||
    "teaching_knowledge_point" in data ||
    "pending_check" in data
  );
}

function hasGuardStatusPayload(data: Record<string, unknown>) {
  return (
    "guard" in data ||
    "allow_tools" in data ||
    "allow_search" in data
  );
}

function buildGuardStageDetail(data: Record<string, unknown>) {
  const guard =
    data.guard && typeof data.guard === "object" && !Array.isArray(data.guard)
      ? (data.guard as Record<string, unknown>)
      : {};
  const allowTools = Boolean(data.allow_tools ?? guard.allow_tools);
  const allowSearch = Boolean(data.allow_search ?? guard.allow_search);
  const reason = typeof guard.reason === "string" ? guard.reason : "";
  const route = typeof data.route === "string" ? data.route : "";
  const routeLabel = ROUTE_LABELS[route] ?? route;
  const notebookPolicy =
    typeof data.notebook_policy === "string"
      ? data.notebook_policy
      : typeof guard.notebook_policy === "string"
        ? guard.notebook_policy
        : "";
  const searchPolicy =
    typeof data.search_policy === "string"
      ? data.search_policy
      : typeof guard.search_policy === "string"
        ? guard.search_policy
        : "";
  return [
    routeLabel ? `路线：${routeLabel}` : "",
    notebookPolicy ? `资料：${NOTEBOOK_POLICY_LABELS[notebookPolicy] ?? notebookPolicy}` : "",
    searchPolicy ? `搜索策略：${SEARCH_POLICY_LABELS[searchPolicy] ?? searchPolicy}` : "",
    `工具：${allowTools ? "允许" : "禁用"}`,
    `搜索：${allowSearch ? "允许" : "禁用"}`,
    reason,
  ].filter(Boolean).join(" · ");
}

function buildTeachingStageDetail(data: Record<string, unknown>) {
  const inputType =
    typeof data.teaching_input_type === "string" ? data.teaching_input_type : "";
  const userState =
    typeof data.teaching_user_state === "string" ? data.teaching_user_state : "";
  const knowledgePoint =
    typeof data.teaching_knowledge_point === "string"
      ? data.teaching_knowledge_point
      : "";
  const parts = [
    QUESTION_TYPE_LABELS[inputType] ?? inputType,
    knowledgePoint,
    userState,
  ].filter(Boolean);

  return parts.length > 0 ? parts.join(" · ") : "已选择适合本轮问题的教学策略。";
}

function buildRetrievalStageDetail(data: Record<string, unknown>) {
  const docCount = Number(data.raw_doc_count ?? data.doc_count ?? 0);
  const isRewritten = Boolean(data.is_rewritten);
  const webSearchUsed = Boolean(data.web_search_used);
  const webSearchAttempted = Boolean(data.web_search_attempted);
  const webSearchError =
    typeof data.web_search_error === "string" ? data.web_search_error : "";
  const diagnosis =
    data.retrieval_diagnosis &&
    typeof data.retrieval_diagnosis === "object" &&
    !Array.isArray(data.retrieval_diagnosis)
      ? String((data.retrieval_diagnosis as Record<string, unknown>).diagnosis ?? "")
      : "";

  let detail = `知识检索命中了 ${docCount} 条内容。`;
  if (docCount === 0) {
    detail = "知识检索没有命中可用内容。";
  }
  if (diagnosis === "empty_knowledge_base") {
    detail = "当前 notebook 暂无可检索资料。";
  } else if (diagnosis === "no_matching_docs") {
    detail = "当前 notebook 没有命中相关资料。";
  } else if (diagnosis === "low_score") {
    detail = `${detail.slice(0, -1)}，但相关度偏低。`;
  }
  if (webSearchUsed) {
    detail = `当前 notebook 未命中足够内容，已使用 Tavily 网络搜索补充 ${docCount} 条上下文。`;
  } else if (webSearchAttempted && webSearchError) {
    detail = `${detail} Tavily 网络搜索失败：${webSearchError}。`;
  } else if (webSearchAttempted) {
    detail = `${detail} 已尝试 Tavily 网络搜索但未获得可用结果。`;
  }
  if (isRewritten) {
    detail = `${detail.slice(0, -1)}，并自动改写了查询。`;
  }
  return detail;
}

function buildContextAuditStageDetail(data: Record<string, unknown>) {
  const audit =
    data.context_audit &&
    typeof data.context_audit === "object" &&
    !Array.isArray(data.context_audit)
      ? (data.context_audit as Record<string, unknown>)
      : {};
  const rawCount = Number(data.raw_doc_count ?? audit.raw_count ?? 0);
  const verifiedCount = Number(data.verified_count ?? audit.verified_count ?? 0);
  const discardedCount = Number(audit.discarded_count ?? Math.max(0, rawCount - verifiedCount));
  const reason = typeof audit.reason === "string" ? audit.reason : "";

  if (verifiedCount > 0) {
    return `上下文审查通过 ${verifiedCount} 条，丢弃 ${discardedCount} 条。`;
  }
  if (rawCount > 0) {
    return `上下文审查未发现可用资料，已丢弃 ${discardedCount || rawCount} 条${reason ? ` · ${reason}` : ""}。`;
  }
  return "上下文审查未发现可用资料。";
}

function buildWebSearchStageDetail(data: Record<string, unknown>) {
  const docCount = Number(data.doc_count ?? 0);
  const webSearchUsed = Boolean(data.web_search_used);
  const webSearchAttempted = Boolean(data.web_search_attempted);
  const webSearchError =
    typeof data.web_search_error === "string" ? data.web_search_error : "";

  if (webSearchUsed) {
    return `Tavily 网络搜索成功，补充 ${docCount} 条上下文。`;
  }
  if (webSearchAttempted && webSearchError) {
    return `Tavily 网络搜索失败：${webSearchError}，已继续使用通用问答兜底。`;
  }
  if (webSearchAttempted) {
    return "已尝试 Tavily 网络搜索，但没有获得可用结果。";
  }
  return "本轮未触发网络搜索。";
}

function buildExecutionInfo(data: Record<string, unknown>): MessageProcessExecution | undefined {
  const executionMode =
    typeof data.execution_mode === "string" ? data.execution_mode : "";
  const profile =
    data.selected_model_profile &&
    typeof data.selected_model_profile === "object" &&
    !Array.isArray(data.selected_model_profile)
      ? (data.selected_model_profile as Record<string, unknown>)
      : null;

  if (!executionMode && !profile && !("degraded" in data)) {
    return undefined;
  }

  return {
    mode: EXECUTION_MODE_LABELS[executionMode] ?? (executionMode || "未知模式"),
    degraded: Boolean(data.degraded),
    modelId: profile && typeof profile.model_id === "string" ? profile.model_id : "",
    modelFamily: profile && typeof profile.family === "string" ? profile.family : "",
    modelProvider: profile && typeof profile.provider === "string" ? profile.provider : "",
    primaryModelId:
      typeof data.primary_model_id === "string" ? data.primary_model_id : undefined,
    fallbackModelId:
      typeof data.fallback_model_id === "string" ? data.fallback_model_id : undefined,
    fallbackUsed: Boolean(data.fallback_used),
    fallbackReason:
      typeof data.fallback_reason === "string" ? data.fallback_reason : undefined,
    modelAttempts: Array.isArray(data.model_attempts)
      ? (data.model_attempts as MessageProcessExecution["modelAttempts"])
      : undefined,
    streamingMode:
      typeof data.streaming_mode === "string" ? data.streaming_mode : undefined,
    modelLatencyMs:
      typeof data.model_latency_ms === "number" ? data.model_latency_ms : undefined,
  };
}

function currentModelOption(config: ModelConfig | null) {
  if (!config) {
    return null;
  }
  return (
    config.available_models.find((item) => item.id === config.current_model) ??
    config.available_models.find((item) => item.id === config.locked_model) ??
    null
  );
}

function currentModelDisplay(config: ModelConfig | null) {
  const option = currentModelOption(config);
  const modelId = config?.locked_model || config?.current_model || "";
  return {
    label: option?.label || modelId || "模型加载中",
    id: option?.id || modelId,
    provider: option?.provider || "",
    family: option?.family || "",
  };
}

function extractQuestionType(
  data: Record<string, unknown>,
  fallback?: string
) {
  if (typeof data.question_type === "string" && data.question_type.trim()) {
    return data.question_type.trim();
  }

  if (
    typeof data.teaching_input_type === "string" &&
    data.teaching_input_type.trim() &&
    data.teaching_input_type !== "check_answer"
  ) {
    return data.teaching_input_type.trim();
  }

  return fallback;
}

function extractRoute(data: Record<string, unknown>, fallback?: string) {
  if (typeof data.route === "string" && data.route.trim()) {
    return data.route.trim();
  }
  return fallback;
}

function buildAnswerContent(
  finalAnswer: string,
  explanation?: Message["explanation"]
) {
  if (finalAnswer.trim()) {
    return finalAnswer.trim();
  }
  const stepContent = (explanation?.steps ?? [])
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
  if (stepContent) {
    return stepContent;
  }
  if (explanation?.topic?.trim()) {
    return `我已经围绕「${explanation.topic.trim()}」整理好讲解了。`;
  }
  return "讲解已经准备好了。";
}

function getCurrentProcessLabel(message: Message) {
  const stages = message.process?.stages ?? [];
  const failedStage = stages.find((stage) => stage.status === "failed");
  if (failedStage?.label) {
    return failedStage.label;
  }
  if (message.quiz && message.quiz.length > 0) {
    return "练习题已准备";
  }
  const answerStage = stages.find(
    (stage) => stage.key === "answer" && stage.status === "completed"
  );
  if (answerStage?.label) {
    return answerStage.label;
  }
  if (message.explanation || message.content.trim()) {
    return "已生成回答";
  }
  const runningStage = stages.find((stage) => stage.status === "running");
  if (runningStage?.label) {
    return runningStage.label;
  }
  const completedStage = [...stages]
    .reverse()
    .find((stage) => stage.status === "completed");
  if (completedStage?.label) {
    return completedStage.label;
  }
  return "已生成回答";
}

function notebookListOrFallback(notebooks: Notebook[]) {
  return notebooks.length > 0 ? notebooks : FALLBACK_NOTEBOOKS;
}

function resolveNotebookId(
  notebooks: Notebook[],
  preferredId?: string | null,
  fallbackId = DEFAULT_NOTEBOOK_ID
) {
  const normalizedNotebooks = notebookListOrFallback(notebooks);
  const normalizedPreferredId = preferredId?.trim();
  if (
    normalizedPreferredId &&
    normalizedNotebooks.some((notebook) => notebook.id === normalizedPreferredId)
  ) {
    return normalizedPreferredId;
  }

  if (normalizedNotebooks.some((notebook) => notebook.id === fallbackId)) {
    return fallbackId;
  }

  return normalizedNotebooks[0]?.id ?? DEFAULT_NOTEBOOK_ID;
}

export default function ChatPage() {
  const { user, isLoading } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState(DEFAULT_NOTEBOOK_ID);
  const [selectedKnowledgeStatus, setSelectedKnowledgeStatus] =
    useState<NotebookKnowledgeStatus | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [showHistory, setShowHistory] = useState(false);
  const activeStreamRef = useRef<AbortController | null>(null);
  const activeDraftSessionRef = useRef<string>("");

  useEffect(() => {
    if (isLoading || !user) {
      return;
    }

    const userId = user.id;
    let isMounted = true;
    const searchParams =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : null;
    const requestedNotebookId =
      searchParams?.get("notebook") ?? searchParams?.get("subject") ?? null;
    const requestedSessionId = searchParams?.get("session") ?? null;

    async function initializePage() {
      setMemory(loadStoredMemory());
      setSessions(mergeStoredChatDraftsWithSessions(loadStoredSessions()));
      setModelConfig(loadStoredModelConfig());

      try {
        const [
          remoteNotebookPayload,
          remoteMemory,
          remoteSessions,
          remoteModelConfig,
        ] = await Promise.all([
          fetchNotebooks().catch(() => []),
          fetchUserMemory(userId).catch(() => null),
          fetchSessions(userId).catch(() => null),
          fetchModelConfig().catch(() => null),
        ]);

        if (!isMounted) {
          return;
        }

        const remoteNotebooks = notebookListOrFallback(remoteNotebookPayload);
        const storedNotebookId = loadStoredNotebookId();
        const fallbackId = resolveNotebookId(
          remoteNotebooks,
          requestedNotebookId ?? storedNotebookId
        );

        setNotebooks(remoteNotebooks);
        setSelectedNotebookId(fallbackId);
        persistStoredNotebookId(fallbackId);

        if (remoteMemory) {
          setMemory(remoteMemory);
          persistMemory(remoteMemory);
        }

        if (remoteSessions) {
          const mergedSessions = mergeStoredChatDraftsWithSessions(remoteSessions);
          setSessions(mergedSessions);
          persistStoredSessions(mergedSessions);

          if (requestedSessionId) {
            const requestedSession = mergedSessions.find(
              (session) => session.id === requestedSessionId
            );

            if (requestedSession) {
              const draft = loadStoredChatDraft(requestedSession.id);
              const sessionNotebookId = resolveNotebookId(
                remoteNotebooks,
                requestedSession.notebookId,
                fallbackId
              );
              setCurrentSessionId(requestedSession.id);
              activeDraftSessionRef.current = requestedSession.id;
              setMessages(draft?.messages ?? requestedSession.messages);
              setSelectedNotebookId(sessionNotebookId);
              persistStoredNotebookId(sessionNotebookId);
            }
          } else {
            const latestDraft = loadLatestStoredChatDraft();
            const draftSession = latestDraft
              ? mergedSessions.find((session) => session.id === latestDraft.sessionId)
              : null;
            if (latestDraft && draftSession) {
              const sessionNotebookId = resolveNotebookId(
                remoteNotebooks,
                latestDraft.notebookId,
                fallbackId
              );
              setCurrentSessionId(latestDraft.sessionId);
              activeDraftSessionRef.current = latestDraft.sessionId;
              setMessages(latestDraft.messages);
              setSelectedNotebookId(sessionNotebookId);
              persistStoredNotebookId(sessionNotebookId);
            }
          }
        } else {
          const latestDraft = loadLatestStoredChatDraft();
          if (latestDraft) {
            const sessionNotebookId = resolveNotebookId(
              remoteNotebooks,
              latestDraft.notebookId,
              fallbackId
            );
            setCurrentSessionId(latestDraft.sessionId);
            activeDraftSessionRef.current = latestDraft.sessionId;
            setMessages(latestDraft.messages);
            setSelectedNotebookId(sessionNotebookId);
            persistStoredNotebookId(sessionNotebookId);
          }
        }

        if (remoteModelConfig) {
          setModelConfig(remoteModelConfig);
          persistStoredModelConfig(remoteModelConfig);
        }

      } catch (error) {
        console.error("加载笔记本列表失败:", error);
      }
    }

    void initializePage();

    return () => {
      isMounted = false;
      activeStreamRef.current?.abort();
      activeStreamRef.current = null;
    };
  }, [isLoading, user]);

  useEffect(() => {
    if (isLoading || !user || !selectedNotebookId) {
      return;
    }

    const activeNotebookId = notebooks.some((notebook) => notebook.id === selectedNotebookId)
      ? selectedNotebookId
      : "";
    if (!activeNotebookId) {
      setSelectedKnowledgeStatus(null);
      return;
    }

    let isMounted = true;
    fetchNotebookKnowledgeStatus(activeNotebookId)
      .then((status) => {
        if (isMounted) {
          setSelectedKnowledgeStatus(status);
        }
      })
      .catch(() => {
        if (isMounted) {
          setSelectedKnowledgeStatus(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isLoading, notebooks, selectedNotebookId, user]);

  function persistDraftMessages(
    draftMessages: Message[],
    sessionId = currentSessionId || activeDraftSessionRef.current,
    notebookId = selectedNotebookId
  ) {
    if (!user || !sessionId || draftMessages.length === 0) {
      return;
    }

    persistStoredChatDraft({
      sessionId,
      notebookId: resolveNotebookId(notebooks, notebookId),
      messages: draftMessages,
      updatedAt: Date.now(),
    });
  }

  function clearCurrentTransientDraft() {
    const sessionId = currentSessionId || activeDraftSessionRef.current;
    if (!sessionId || sessions.some((session) => session.id === sessionId)) {
      return;
    }

    clearStoredChatDraft(sessionId);
  }

  function updateLastAssistant(updater: (message: Message) => Message) {
    setMessages((previous) => {
      const next = [...previous];

      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === "assistant") {
          next[index] = updater(next[index]);
          break;
        }
      }

      persistDraftMessages(next);
      return next;
    });
  }

  async function refreshNotebooks() {
    const data = notebookListOrFallback(await fetchNotebooks().catch(() => []));
    setNotebooks(data);
    const nextNotebookId = resolveNotebookId(data, selectedNotebookId);
    if (nextNotebookId !== selectedNotebookId) {
      setSelectedNotebookId(nextNotebookId);
      persistStoredNotebookId(nextNotebookId);
    }
  }

  async function refreshSessions() {
    if (!user) {
      return false;
    }
    try {
      const remoteSessions = await fetchSessions(user.id);
      const mergedSessions = mergeStoredChatDraftsWithSessions(remoteSessions);
      setSessions(mergedSessions);
      persistStoredSessions(mergedSessions);
      return true;
    } catch (error) {
      console.error("刷新聊天记录失败:", error);
      return false;
    }
  }

  function handleNotebookSelect(notebookId: string) {
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;
    clearCurrentTransientDraft();
    activeDraftSessionRef.current = "";
    setIsStreaming(false);
    const nextNotebookId = resolveNotebookId(notebooks, notebookId);
    setSelectedNotebookId(nextNotebookId);
    persistStoredNotebookId(nextNotebookId);
    setMessages([]);
    setCurrentSessionId("");
  }

  function handleNewSession() {
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;
    clearCurrentTransientDraft();
    activeDraftSessionRef.current = "";
    setIsStreaming(false);
    setMessages([]);
    setCurrentSessionId("");
    setShowHistory(false);
  }

  async function handleUpload(file: File) {
    setIsUploading(true);

    try {
      const result = await uploadPDFToNotebook(file, selectedNotebookId);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `资料已加入“我的补充资料”：${result.filename}，共 ${result.total_pages} 页，切成 ${result.total_chunks} 个个人知识块。`,
          timestamp: Date.now(),
        },
      ]);

      await refreshNotebooks();
      fetchNotebookKnowledgeStatus(selectedNotebookId)
        .then(setSelectedKnowledgeStatus)
        .catch(() => undefined);
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `上传失败：${
            error instanceof Error ? error.message : "未知错误"
          }`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsUploading(false);
    }
  }

  function handleSend(question: string) {
    if (!user) {
      return;
    }

    activeStreamRef.current?.abort();
    activeStreamRef.current = null;

    const sessionId = currentSessionId || crypto.randomUUID();
    const userMessage: Message = {
      role: "user",
      content: question,
      timestamp: Date.now(),
    };

    const assistantMessage: Message = {
      role: "assistant",
      content: "",
      timestamp: Date.now() + 1,
      process: createInitialProcess(),
    };

    if (!currentSessionId) {
      setCurrentSessionId(sessionId);
    }
    activeDraftSessionRef.current = sessionId;

    setMessages((previous) => {
      const next = [...previous, userMessage, assistantMessage];
      persistDraftMessages(next, sessionId, selectedNotebookId);
      return next;
    });
    setIsStreaming(true);

    activeStreamRef.current = sendChatSSE(
      user.id,
      question,
      (event) => {
        const data = event.data as Record<string, unknown>;

        switch (event.event) {
          case "status": {
            if (data.finalized === true) {
              updateLastAssistant((message) => {
                const nextProcess = cloneProcess(message.process);
                nextProcess.stages = finalizeRunningStages(nextProcess.stages);
                nextProcess.currentStage = getCurrentProcessLabel({
                  ...message,
                  process: nextProcess,
                });

                return {
                  ...message,
                  process: nextProcess,
                };
              });
              break;
            }

            if (hasGuardStatusPayload(data)) {
              updateLastAssistant((message) => {
                const route = extractRoute(data, message.route);
                return {
                  ...message,
                  route,
                  process: upsertProcessStage(
                    message.process,
                    {
                      key: "guard",
                      label: "工具守卫",
                      status: "completed",
                      detail: buildGuardStageDetail(data),
                      elapsed:
                        typeof data.elapsed === "number" ? data.elapsed : undefined,
                    },
                    "工具守卫已完成"
                  ),
                };
              });
              break;
            }

            if (hasWebSearchStatusPayload(data)) {
              const toolCalls = normalizeToolCalls(data.external_tool_calls);
              updateLastAssistant((message) => {
                const questionType = extractQuestionType(data, message.questionType);
                const route = extractRoute(data, message.route);
                const nextProcess = upsertProcessStage(
                  message.process,
                  {
                    key: "web_search",
                    label: "网络搜索",
                    status: Boolean(data.web_search_used) ? "completed" : "completed",
                    detail: buildWebSearchStageDetail(data),
                    elapsed:
                      typeof data.elapsed === "number" ? data.elapsed : undefined,
                  },
                  "网络搜索完成"
                );

                if (toolCalls.length > 0) {
                  nextProcess.toolCalls = mergeProcessToolCalls(
                    nextProcess.toolCalls,
                    toolCalls
                  );
                }

                return {
                  ...message,
                  questionType,
                  route,
                  process: nextProcess,
                };
              });
              break;
            }

            if (hasContextAuditStatusPayload(data)) {
              updateLastAssistant((message) => {
                const questionType = extractQuestionType(data, message.questionType);
                const route = extractRoute(data, message.route);
                return {
                  ...message,
                  questionType,
                  route,
                  process: upsertProcessStage(
                    message.process,
                    {
                      key: "context_audit",
                      label: "上下文审查",
                      status: "completed",
                      detail: buildContextAuditStageDetail(data),
                      elapsed:
                        typeof data.elapsed === "number" ? data.elapsed : undefined,
                    },
                    "上下文审查完成"
                  ),
                };
              });
              break;
            }

            if (hasRetrievalStatusPayload(data)) {
              const toolCalls = normalizeToolCalls(data.external_tool_calls);
              updateLastAssistant((message) => {
                const questionType = extractQuestionType(data, message.questionType);
                const route = extractRoute(data, message.route);
                const nextProcess = upsertProcessStage(
                  message.process,
                  {
                    key: "retrieval",
                    label: "知识检索",
                    status: "completed",
                    detail: buildRetrievalStageDetail(data),
                    elapsed:
                      typeof data.elapsed === "number" ? data.elapsed : undefined,
                  },
                  "知识检索完成"
                );

                if (toolCalls.length > 0) {
                  nextProcess.toolCalls = mergeProcessToolCalls(
                    nextProcess.toolCalls,
                    toolCalls
                  );
                }

                return {
                  ...message,
                  questionType,
                  route,
                  process: nextProcess,
                };
              });
              break;
            }

            if (hasTeachingStatusPayload(data)) {
              updateLastAssistant((message) => {
                const questionType = extractQuestionType(data, message.questionType);
                const route = extractRoute(data, message.route);
                return {
                  ...message,
                  questionType,
                  route,
                  process: upsertProcessStage(
                    message.process,
                    {
                      key: "teaching",
                      label: "教学策略",
                      status: "completed",
                      detail: buildTeachingStageDetail(data),
                      elapsed:
                        typeof data.elapsed === "number" ? data.elapsed : undefined,
                    },
                    "教学策略已确定"
                  ),
                };
              });
              break;
            }

            if (data.heartbeat === true) {
              updateLastAssistant((message) => ({
                ...message,
                process: upsertProcessStage(
                  message.process,
                  {
                    key: "heartbeat",
                    label: "处理中",
                    status: "running",
                    detail:
                      typeof data.message === "string"
                        ? data.message
                        : "仍在处理，本轮可能需要更久。",
                  },
                  "处理中",
                  { completeRunning: false }
                ),
              }));
              break;
            }

            updateLastAssistant((message) => ({
              ...message,
              process: upsertProcessStage(
                message.process,
                {
                  key: "status",
                  label: "准备中",
                  status: "running",
                  detail:
                    typeof data.message === "string"
                      ? data.message
                      : "已连接学习引擎，正在准备处理。",
                },
                "准备中",
                { completeRunning: false }
              ),
            }));
            break;
          }

          case "routing": {
            const rawQuestionType = String(data.question_type ?? "concept");
            const questionType =
              QUESTION_TYPE_LABELS[rawQuestionType] ?? rawQuestionType;
            const rawRoute = typeof data.route === "string" ? data.route : "";
            const route = ROUTE_LABELS[rawRoute] ?? rawRoute;
            const notebookPolicy =
              typeof data.notebook_policy === "string" ? data.notebook_policy : "";
            const searchPolicy =
              typeof data.search_policy === "string" ? data.search_policy : "";
            const policyDetail = [
              notebookPolicy ? NOTEBOOK_POLICY_LABELS[notebookPolicy] ?? notebookPolicy : "",
              searchPolicy ? SEARCH_POLICY_LABELS[searchPolicy] ?? searchPolicy : "",
            ].filter(Boolean).join(" · ");

            updateLastAssistant((message) => ({
              ...message,
              questionType: rawQuestionType,
              route: rawRoute || message.route,
              process: upsertProcessStage(
                message.process,
                {
                  key: "routing",
                  label: "问题识别",
                  status: "completed",
                  detail: `已识别为${questionType}${route ? ` · 路线：${route}` : ""}${policyDetail ? ` · ${policyDetail}` : ""}。`,
                  elapsed:
                    typeof data.elapsed === "number" ? data.elapsed : undefined,
                },
                "问题识别完成"
              ),
            }));
            break;
          }

          case "retrieval": {
            const toolCalls = normalizeToolCalls(data.external_tool_calls);
            updateLastAssistant((message) => {
              const nextProcess = upsertProcessStage(
                message.process,
                {
                  key: "retrieval",
                  label: "知识检索",
                  status: "completed",
                  detail: buildRetrievalStageDetail(data),
                  elapsed:
                    typeof data.elapsed === "number" ? data.elapsed : undefined,
                },
                "知识检索完成"
              );

              if (toolCalls.length > 0) {
                nextProcess.toolCalls = mergeProcessToolCalls(
                  nextProcess.toolCalls,
                  toolCalls
                );
              }

              return {
                ...message,
                process: nextProcess,
              };
            });
            break;
          }

          case "explanation": {
            const explanation = normalizeExplanationPayload(
              data.explanation as Message["explanation"] | undefined
            );
            const finalAnswer =
              typeof data.final_answer === "string" ? data.final_answer : "";
            const execution = buildExecutionInfo(data);
            const toolCalls = mergeToolCalls(
              data.tool_calls,
              data.external_tool_calls
            );
            const reasoningSummary =
              typeof data.reasoning_summary === "string"
                ? data.reasoning_summary.trim()
                : "";
            const toolDecisionRounds = Array.isArray(data.tool_decision_rounds)
              ? data.tool_decision_rounds
              : [];
            const eventQuestionType = extractQuestionType(data);
            const eventRoute = extractRoute(data);

            if (
              !explanation &&
              !finalAnswer &&
              !execution &&
              toolCalls.length === 0 &&
              !reasoningSummary &&
              toolDecisionRounds.length === 0
            ) {
              break;
            }

            updateLastAssistant((message) => {
              let nextProcess = upsertProcessStage(
                message.process,
                {
                  key: "answer",
                  label: "已生成回答",
                  status: "completed",
                  detail: finalAnswer
                    ? "已生成最终回答。"
                    : "已生成结构化讲解。",
                  elapsed:
                    typeof data.elapsed === "number" ? data.elapsed : undefined,
                },
                "已生成回答"
              );

              nextProcess.reasoningSummary =
                reasoningSummary ||
                explanation?.thinking ||
                finalAnswer ||
                nextProcess.reasoningSummary ||
                "";

              if (toolDecisionRounds.length > 0) {
                const usedToolCount = toolDecisionRounds.filter((item) => {
                  if (!item || typeof item !== "object") {
                    return false;
                  }
                  const tool = String((item as Record<string, unknown>).tool ?? "");
                  return tool.length > 0 && tool !== "none";
                }).length;
                nextProcess = upsertProcessStage(
                  nextProcess,
                  {
                    key: "tool_decision",
                    label: "工具决策",
                    status: "completed",
                    detail:
                      usedToolCount > 0
                        ? `模型完成 ${toolDecisionRounds.length} 轮工具判断，调用了 ${usedToolCount} 次工具。`
                        : `模型完成 ${toolDecisionRounds.length} 轮工具判断，决定直接回答。`,
                  },
                  "已生成回答"
                );
              }

              if (execution) {
                nextProcess.execution = execution;
                nextProcess = upsertProcessStage(
                  nextProcess,
                  {
                    key: "execution",
                    label: "模型执行",
                    status: "completed",
                    detail: [
                      execution.mode,
                      execution.modelFamily,
                      execution.modelId,
                      execution.degraded ? "已降级回退" : "",
                      execution.fallbackUsed && execution.primaryModelId && execution.fallbackModelId
                        ? `已从 ${execution.primaryModelId} 回滚到 ${execution.fallbackModelId}`
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" · "),
                    elapsed:
                      typeof data.elapsed === "number" ? data.elapsed : undefined,
                  },
                  "已生成回答"
                );
              }

              if (toolCalls.length > 0) {
                nextProcess.toolCalls = mergeProcessToolCalls(
                  nextProcess.toolCalls,
                  toolCalls
                );
              }

              return {
                ...message,
                content: buildAnswerContent(finalAnswer, explanation),
                explanation,
                questionType: eventQuestionType ?? message.questionType,
                route: eventRoute ?? message.route,
                process: nextProcess,
              };
            });
            break;
          }

          case "answer_delta": {
            const delta = typeof data.delta === "string" ? data.delta : "";
            if (!delta) {
              break;
            }
            updateLastAssistant((message) => {
              const nextProcess = upsertProcessStage(
                message.process,
                {
                  key: "answer_stream",
                  label: "正在生成回答",
                  status: "running",
                  detail:
                    data.streaming_mode === "token"
                      ? "正在接收模型流式片段。"
                      : "正在展示节点级回答片段。",
                  elapsed:
                    typeof data.elapsed === "number" ? data.elapsed : undefined,
                },
                "正在生成回答",
                { completeRunning: false }
              );
              nextProcess.reasoningSummary =
                nextProcess.reasoningSummary ||
                "当前为节点级流式：模型/工具节点完成后立即展示结果，不展示原始思维链。";
              return {
                ...message,
                content: `${message.content || ""}${delta}`,
                process: nextProcess,
              };
            });
            break;
          }

          case "quiz": {
            const quizItems: QuizItem[] = Array.isArray(data.quiz_items)
              ? (data.quiz_items as QuizItem[])
              : [];
            const quizRequest =
              data.quiz_request && typeof data.quiz_request === "object"
                ? (data.quiz_request as QuizRequestResolution)
                : undefined;
            const quizClarification =
              data.quiz_clarification && typeof data.quiz_clarification === "object"
                ? (data.quiz_clarification as QuizClarificationPanel)
                : undefined;
            const finalAnswer =
              typeof data.final_answer === "string" ? data.final_answer : "";
            const quizGenerationStatus =
              data.quiz_generation_status &&
              typeof data.quiz_generation_status === "object" &&
              !Array.isArray(data.quiz_generation_status)
                ? (data.quiz_generation_status as Record<string, unknown>)
                : {};
            const qualityFailureSummary =
              typeof quizGenerationStatus.quality_failure_summary === "string"
                ? quizGenerationStatus.quality_failure_summary
                : "";
            const eventQuestionType = extractQuestionType(data);
            const eventRoute = extractRoute(data);

            if (quizItems.length > 0) {
              if (quizRequest?.should_switch_topic) {
                clearStoredPracticeState();
              }
              persistQuiz(quizItems, {
                topic: quizRequest?.requested_topic || quizRequest?.active_topic || quizRequest?.topic || quizItems[0]?.knowledge_point,
                subjectId: quizRequest?.subject_id || selectedNotebookId,
                sessionId,
                shouldSwitchTopic: Boolean(quizRequest?.should_switch_topic),
              });
            }

            updateLastAssistant((message) => {
              const nextProcess = upsertProcessStage(
                message.process,
                {
                  key: "answer",
                  label: "练习题已准备",
                  status: "completed",
                  detail:
                    quizItems.length > 0
                      ? `已准备 ${quizItems.length} 道练习题，并同步生成了最终回答。`
                      : quizClarification
                        ? "需要先确认练习方向。"
                        : qualityFailureSummary
                          ? `练习题未保存：${qualityFailureSummary}`
                          : "练习题结果已经准备好了。",
                  elapsed:
                    typeof data.elapsed === "number" ? data.elapsed : undefined,
                },
                "练习题已准备"
              );

              return {
                ...message,
                content:
                  finalAnswer ||
                  (quizClarification
                    ? "我可以帮你出题，但需要先确定练习方向。"
                    : "") ||
                  message.content ||
                  "我顺手帮你准备了一组练习题，去刷题页就能接着做。",
                questionType: eventQuestionType ?? message.questionType ?? "practice",
                route: eventRoute ?? message.route,
                quiz: quizItems.length > 0 ? quizItems : undefined,
                quizRequest: quizRequest ?? message.quizRequest,
                quizClarification: quizClarification ?? message.quizClarification,
                process: nextProcess,
              };
            });
            break;
          }

          case "memory": {
            if (!data.memory) {
              break;
            }

            const nextMemory = normalizeMemoryPayload(data.memory);
            setMemory(nextMemory);
            persistMemory(nextMemory);
            break;
          }

          case "error": {
            const reason = typeof data.reason === "string" ? data.reason : undefined;
            const retryable = typeof data.retryable === "boolean" ? data.retryable : true;
            const rawError =
              typeof data.error === "string" && data.error.trim()
                ? data.error.trim()
                : "学习引擎处理失败，请稍后重试。";
            const failure = buildChatFailurePresentation(rawError, reason, retryable);
            updateLastAssistant((message) => {
              return {
                ...message,
                content: failure.message,
                process: upsertProcessStage(
                  message.process,
                  {
                    key: "error",
                    label: failure.label,
                    status: "failed",
                    detail: failure.message,
                  },
                  failure.label,
                  { completeRunning: false }
                ),
              };
            });
            activeStreamRef.current = null;
            setIsStreaming(false);
            break;
          }

          default:
            break;
        }
      },
      () => {
        updateLastAssistant((message) => {
          const nextProcess = cloneProcess(message.process);
          nextProcess.stages = finalizeRunningStages(nextProcess.stages);
          nextProcess.currentStage = getCurrentProcessLabel(message);

          return {
            ...message,
            content: message.content || nextProcess.reasoningSummary || "这轮学习已经处理完成。",
            process: nextProcess,
          };
        });
        activeStreamRef.current = null;
        setIsStreaming(false);
        void refreshSessions().then((synced) => {
          if (synced) {
            clearStoredChatDraft(sessionId);
          }
        });
      },
      (error) => {
        updateLastAssistant((message) => {
          const errorRecord =
            error && typeof error === "object"
              ? (error as Error & { reason?: string; retryable?: boolean })
              : undefined;
          const rawErrorMessage =
            error instanceof Error && error.message
              ? error.message
              : "学习引擎连接中断，请稍后重试。";
          const failure = buildChatFailurePresentation(
            rawErrorMessage,
            errorRecord?.reason,
            errorRecord?.retryable ?? true
          );
          return {
            ...message,
            content: failure.message,
            process: upsertProcessStage(
              message.process,
              {
                key: "error",
                label: failure.label,
                status: "failed",
                detail: failure.message,
              },
              failure.label,
              { completeRunning: false }
            ),
          };
        });
        activeStreamRef.current = null;
        setIsStreaming(false);
      },
      {
        notebookId: selectedNotebookId,
        sessionId,
        idleTimeoutMs: 90000,
        maxConnectRetries: 2,
        onRetry: (attempt, maxRetries) => {
          updateLastAssistant((message) => ({
            ...message,
            process: upsertProcessStage(
              message.process,
              {
                key: "connection_retry",
                label: "连接恢复中",
                status: "running",
                detail: `学习引擎连接失败，正在自动重试 ${attempt}/${maxRetries}。`,
              },
              "连接恢复中",
              { completeRunning: false }
            ),
          }));
        },
      }
    );
  }

  const visibleNotebooks = notebookListOrFallback(notebooks);
  const selectedNotebook = visibleNotebooks.find(
    (notebook) => notebook.id === selectedNotebookId
  );
  const currentSession = sessions.find((session) => session.id === currentSessionId);
  const currentSessionNotebook = currentSession
    ? visibleNotebooks.find((notebook) => notebook.id === currentSession.notebookId) ?? null
    : selectedNotebook ?? null;
  const modelDisplay = currentModelDisplay(modelConfig);
  const shouldShowKnowledgeHint =
    selectedKnowledgeStatus &&
    selectedKnowledgeStatus.coverage_level !== "ready";
  const knowledgeHintAction =
    selectedKnowledgeStatus?.suggested_actions[0] ??
    "可以上传 PDF 作为我的补充资料，让回答更贴近你的学习材料。";

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-4">
        <div className="neo-card-secondary w-full p-5 text-center">
          <p className="neo-label">Notebook Tutor</p>
          <p className="mt-3 text-lg font-black">正在恢复你的学习空间…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="neo-label">Notebook Tutor</p>
            <h1 className="mt-2 inline-block -rotate-1 border-[3px] border-neo-ink bg-white px-4 py-2 text-3xl font-black tracking-tight shadow-neo-sm">
              学习助手
            </h1>
            <p className="mt-3 max-w-xs text-sm font-bold leading-relaxed">
              围绕你的笔记本来学，还会记住你卡住的地方。
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={showHistory ? "关闭聊天历史" : "打开聊天历史"}
              onClick={() => setShowHistory(true)}
              className="group flex flex-col items-center gap-1 transition-transform hover:-translate-y-1"
            >
              <div className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border-[3px] border-neo-ink bg-white shadow-neo-sm">
                <Clock size={18} strokeWidth={2.8} className="text-neo-ink" />
              </div>
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-6">
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <NotebookSelector
                notebooks={visibleNotebooks}
                selectedId={selectedNotebookId}
                onSelect={handleNotebookSelect}
              />
            </div>
          </div>

          {modelConfig && (
            <div className="flex items-center justify-between rounded-[1rem] border-[3px] border-neo-ink bg-neo-muted px-4 py-2 shadow-neo-sm">
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded-full border-2 border-neo-ink bg-green-500 animate-pulse" />
                <div className="min-w-0">
                  <span className="block truncate text-xs font-black uppercase tracking-widest text-neo-ink">
                    {modelDisplay.label}
                  </span>
                  <span className="block truncate text-[10px] font-bold text-neo-ink/60">
                    {[modelDisplay.provider, modelDisplay.family, modelDisplay.id]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
              </div>
              <span className="text-xs font-bold text-neo-ink/70">当前启用</span>
            </div>
          )}

          {shouldShowKnowledgeHint && (
            <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
              <div className="flex items-center justify-between gap-3">
                <p className="neo-label">{COVERAGE_LABELS[selectedKnowledgeStatus.coverage_level]}</p>
                <span className="neo-badge bg-neo-muted">
                  完整度 {selectedKnowledgeStatus.coverage_score}
                </span>
              </div>
              <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
                当前 notebook 资料还不够完整，RAG 会优先使用已命中的内容，但可能需要补资料才能回答得更准。
                {selectedKnowledgeStatus.personal_doc_count > 0
                  ? ` 已加载 ${selectedKnowledgeStatus.personal_doc_count} 条我的补充资料。`
                  : " 你也可以上传 PDF，补充内容仅自己可见。"}
              </p>
              <p className="mt-2 border-l-[4px] border-neo-ink bg-neo-bg px-3 py-2 text-xs font-black text-neo-ink">
                建议：{knowledgeHintAction}
              </p>
            </div>
          )}

          {currentSession && hasSessionSummary(currentSession.sessionMemory) && (
            <SessionSummaryCard
              session={currentSession}
              notebook={currentSessionNotebook}
              title="当前会话进度"
              compact
            />
          )}

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Sparkles size={16} strokeWidth={2.8} />
              <p className="neo-label">Notebook Feed</p>
            </div>

            <ChatWindow
              messages={messages}
              isStreaming={isStreaming}
              onSuggestionClick={handleSend}
            />
          </section>
        </div>
      </main>

      <div className="sticky bottom-0 z-10 border-t-[3px] border-neo-ink bg-neo-bg px-4 pb-20 pt-4">
        <InputBar
          onSend={handleSend}
          onUpload={handleUpload}
          disabled={isStreaming}
          isUploading={isUploading}
          placeholder={`围绕「${selectedNotebook?.name ?? "选择知识库辅助参考"}」开始提问...`}
        />
      </div>

      <BottomNav />

      <HistoryDrawer
        isOpen={showHistory}
        onClose={() => setShowHistory(false)}
        sessions={sessions}
        notebooks={visibleNotebooks}
        currentSessionId={currentSessionId}
        onSelectSession={(session) => {
          activeStreamRef.current?.abort();
          activeStreamRef.current = null;
          setIsStreaming(false);
          const sessionNotebookId = resolveNotebookId(
            visibleNotebooks,
            session.notebookId
          );
          setSelectedNotebookId(sessionNotebookId);
          persistStoredNotebookId(sessionNotebookId);
          setCurrentSessionId(session.id);
          activeDraftSessionRef.current = session.id;
          setMessages(session.messages);
          setShowHistory(false);
        }}
        onDeleteSession={(id) => {
          void deleteSessionRemote(user.id, id)
            .then(() => refreshSessions())
            .catch((error) => {
              console.error("删除聊天记录失败:", error);
            });
          if (currentSessionId === id) {
            handleNewSession();
          }
        }}
        onNewSession={handleNewSession}
      />

    </div>
  );
}
