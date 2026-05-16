import { useEffect, useMemo, useRef, useState } from "react";
import Taro, { useDidShow, useUnload } from "@tarojs/taro";
import { Button, ScrollView, Text, Textarea, View } from "@tarojs/components";
import { deleteSession, ensureAuthSession, fetchModelHealth, fetchNotebooks, fetchSessions } from "@/services/api";
import { sendChatStream } from "@/services/chat-stream";
import { buildChatStreamPayload, dedupeDisplayAnswer } from "@/services/chat-stream-core";
import { requireAuthUser } from "@/store/auth";
import {
  clearChatDraft,
  clearStoredSessionId,
  createSessionId,
  getChatDraft,
  getStoredNotebookId,
  getStoredSessionId,
  appendStoredQuiz,
  setChatDraft,
  setLearningStoreUser,
  setStoredMemory,
  setStoredNotebookId,
  setStoredSessionId
} from "@/store/learning";
import {
  DEFAULT_NOTEBOOK_ID,
  type ChatMessage,
  type ChatProcess,
  type ChatProcessExecution,
  type ChatProcessStage,
  type ChatStreamDiagnostics,
  type ChatProcessToolCall,
  type ChatSession,
  type Explanation,
  type Notebook,
  type QuizClarificationPanel,
  type QuizItem,
  type QuizRequestResolution
} from "@/types/api";
import "./index.scss";

const STARTER_MESSAGES: ChatMessage[] = [
  {
    role: "assistant",
    content: "你好，我是你的学习助手。可以问知识点、让我拆题，也可以直接让我出几道练习。",
    timestamp: Date.now()
  }
];

const TOOL_LABELS: Record<string, string> = {
  notebook_retrieve: "笔记本检索",
  search_notebook_context: "笔记本检索",
  web_search: "网络搜索",
  tavily_web_search: "网络搜索",
  mcp_web_search: "网络搜索",
  web_extract: "网页读取",
  mcp_web_read: "网页读取",
  session_summary: "会话摘要",
  get_session_summary: "会话摘要",
  learning_profile: "学习画像",
  get_user_learning_profile: "学习画像",
  question_recommend: "题目推荐",
  recommend_questions: "题目推荐"
};

const EXECUTION_MODE_LABELS: Record<string, string> = {
  orchestrator_graph: "Graph 编排",
  deterministic_context: "确定性上下文",
  direct_answer: "直接回答",
  tool_calling: "工具调用"
};

type AnswerBlock =
  | { type: "heading" | "paragraph" | "code"; text: string }
  | { type: "ordered" | "unordered"; items: string[] };

interface StreamPresentation {
  mode?: string;
  deltaCount: number;
  synthetic: boolean;
  active: boolean;
}

const NODE_REPLAY_INTERVAL_MS = 110;
const CHAT_DEBUG_PROCESS = (process.env.TARO_APP_CHAT_DEBUG_PROCESS || "false").toLowerCase() === "true";

function safeText(value: any) {
  return typeof value === "string" ? value.trim() : "";
}

function safeCount(value: any): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function safeModelAttempts(value: any) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];
}

function inferCallStatus(data: any, attempts: any[], streamingTokenCount?: number) {
  const explicitStatus = safeText(data?.call_status || data?.callStatus);
  if (explicitStatus) return explicitStatus;
  if (Boolean(data?.fallback_used || data?.fallbackUsed)) return "fallback";
  if (attempts.some((item) => safeText(item?.status).toLowerCase() === "ok")) return "ok";
  if (typeof streamingTokenCount === "number" && streamingTokenCount > 0) return "ok";
  if (Boolean(data?.degraded)) return "failed";
  return attempts.length ? "unknown" : "";
}

function callStatusLabel(status?: string) {
  const normalized = safeText(status).toLowerCase();
  if (normalized === "ok" || normalized === "success") return "模型已调用";
  if (normalized === "fallback") return "备用模型已调用";
  if (normalized === "failed" || normalized === "error") return "模型调用异常";
  if (normalized === "unknown") return "模型状态待确认";
  return status || "模型执行";
}

function streamingDegradedText(reason?: string) {
  const normalized = safeText(reason);
  if (!normalized) return "";
  if (
    normalized === "cloud_container_transport"
    || normalized === "cloud_container_transport_retry"
    || normalized === "cloud_container_error"
  ) {
    return CHAT_DEBUG_PROCESS ? `流式降级原因：${normalized}` : "当前环境使用云托管同步请求。";
  }
  if (normalized === "chat_async_job_pending") {
    return "正在后台整理完整答案。";
  }
  if (normalized === "provider_stream_returned_no_chunks") {
    return CHAT_DEBUG_PROCESS ? "后端模型流没有返回 token 片段，已按节点级展示。" : "已切换为同步展示。";
  }
  if (normalized === "chunk_receiver_unavailable") {
    return CHAT_DEBUG_PROCESS ? "当前小程序环境未提供 chunk 接收能力，已使用同步请求。" : "当前环境使用云托管同步请求。";
  }
  if (normalized === "node_synthetic_delta") {
    return CHAT_DEBUG_PROCESS ? "后端返回的是节点级回答片段，未收到真实 token 流。" : "正在展示完整回答。";
  }
  if (/timeout/i.test(normalized)) {
    return CHAT_DEBUG_PROCESS ? "流式连接超时，已进入可控错误或降级处理。" : "云端正在整理答案。";
  }
  return CHAT_DEBUG_PROCESS ? `流式降级原因：${normalized}` : "已切换为同步展示。";
}

function stringifyToolArg(value: any): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function summarizeToolArgs(name: string, args: any) {
  if (typeof args === "string" && args.trim()) return args.trim();
  if (!args || typeof args !== "object" || Array.isArray(args)) return "无额外参数";

  const parts: string[] = [];
  const pushArg = (label: string, key: string) => {
    const value = stringifyToolArg(args[key]);
    if (value) parts.push(`${label}=${value}`);
  };

  if (name.includes("notebook") || name.includes("retrieve")) {
    pushArg("query", "query");
    pushArg("top_k", "top_k");
  } else if (name.includes("search")) {
    pushArg("query", "query");
    pushArg("max_results", "max_results");
  } else if (name.includes("read") || name.includes("extract")) {
    pushArg("url", "url");
  } else {
    Object.keys(args).slice(0, 3).forEach((key) => pushArg(key, key));
  }

  return parts.length ? parts.join(" · ") : "无额外参数";
}

function normalizeToolCalls(rawToolCalls: any): ChatProcessToolCall[] {
  if (!Array.isArray(rawToolCalls)) return [];
  return rawToolCalls.reduce<ChatProcessToolCall[]>((items, item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return items;
    const name = safeText(item.capability || item.name || item.tool);
    const label = safeText(item.label) || TOOL_LABELS[name] || name || "未知工具";
    const docCount = safeCount(item.doc_count ?? item.docCount);
    items.push({
      name,
      label,
      success: item.success === undefined ? !item.error : Boolean(item.success),
      argsSummary: safeText(item.argsSummary) || summarizeToolArgs(name, item.args),
      error: safeText(item.error) || undefined,
      docCount
    });
    return items;
  }, []);
}

function mergeToolCalls(...sources: any[]): ChatProcessToolCall[] {
  const seen = new Set<string>();
  return sources
    .flatMap((source) => normalizeToolCalls(source))
    .filter((toolCall) => {
      const key = `${toolCall.name}:${toolCall.argsSummary}:${toolCall.success}:${toolCall.error || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function mergeProcessToolCalls(
  current: ChatProcessToolCall[] | undefined,
  incoming: ChatProcessToolCall[]
) {
  return mergeToolCalls(current || [], incoming);
}

function buildExecutionInfo(data: any): ChatProcessExecution | undefined {
  const rawProfile = data?.selected_model_profile || data?.selectedModelProfile;
  const profile = rawProfile && typeof rawProfile === "object"
    ? rawProfile
    : {};
  const executionMode = safeText(data?.execution_mode || data?.executionMode);
  const streamingMode = safeText(data?.streaming_mode || data?.streamingMode);
  const streamingTokenCount = safeCount(data?.streaming_token_count ?? data?.streamingTokenCount);
  const modelAttempts = safeModelAttempts(data?.model_attempts ?? data?.modelAttempts);
  const execution: ChatProcessExecution = {
    mode: EXECUTION_MODE_LABELS[executionMode] || executionMode || (streamingMode ? "流式执行" : ""),
    degraded: Boolean(data?.degraded),
    modelId: safeText(profile.model_id || profile.modelId || data?.model_id || data?.modelId),
    modelFamily: safeText(profile.family || data?.modelFamily),
    modelProvider: safeText(profile.provider || data?.modelProvider),
    primaryModelId: safeText(data?.primary_model_id || data?.primaryModelId),
    fallbackModelId: safeText(data?.fallback_model_id || data?.fallbackModelId),
    fallbackUsed: Boolean(data?.fallback_used || data?.fallbackUsed),
    fallbackReason: safeText(data?.fallback_reason || data?.fallbackReason),
    streamingMode,
    streamingTokenCount,
    streamingDegradedReason: safeText(data?.streaming_degraded_reason || data?.streamingDegradedReason),
    modelLatencyMs: safeCount(data?.model_latency_ms ?? data?.modelLatencyMs),
    modelAttempts,
    callStatus: inferCallStatus(data, modelAttempts, streamingTokenCount)
  };
  const hasExecutionData = Object.entries(execution).some(([, value]) => {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return Number.isFinite(value);
    if (Array.isArray(value)) return value.length > 0;
    return Boolean(value);
  });
  return hasExecutionData ? execution : undefined;
}

function stripMarkdownArtifacts(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[a-zA-Z]*\n?/g, "").replace(/```/g, ""))
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function normalizeAnswerLine(line: string) {
  const trimmed = line.trim();
  if (!trimmed) return "";
  const pipeParts = trimmed.split("|").map((part) => part.trim()).filter(Boolean);
  if (pipeParts.length >= 3) {
    return pipeParts.join(" · ");
  }
  return trimmed;
}

function sanitizeAnswerText(text: string) {
  const normalized = stripMarkdownArtifacts(text)
    .replace(/\r\n/g, "\n")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/gm, "\n")
    .replace(/\|{2,}/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .replace(/([。！？；：])\s*(\d+[.、]\s*)/g, "$1\n$2")
    .replace(/([^\n])\s+(\d+[.、]\s+)/g, "$1\n$2")
    .replace(/([^\n])\s+(\*\s+)/g, "$1\n$2")
    .replace(/([^\n])\s+(-\s+(?!\d))/g, "$1\n$2")
    .split("\n")
    .map(normalizeAnswerLine)
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return dedupeDisplayAnswer(normalized);
}

function flushParagraph(lines: string[], blocks: AnswerBlock[]) {
  if (!lines.length) return;
  const text = lines.join("\n").trim();
  if (!text) return;
  const isHeading = text.length <= 24 && /[:：]$/.test(text);
  blocks.push({ type: isHeading ? "heading" : "paragraph", text });
  lines.length = 0;
}

function pushListBlock(blocks: AnswerBlock[], type: "ordered" | "unordered", item: string) {
  const last = blocks[blocks.length - 1];
  if (last?.type === type) {
    last.items.push(item);
    return;
  }
  blocks.push({ type, items: [item] });
}

function answerBlocks(text: string): AnswerBlock[] {
  const normalized = sanitizeAnswerText(text);
  if (!normalized) return [];
  const blocks: AnswerBlock[] = [];
  const paragraphLines: string[] = [];
  normalized.split("\n").forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph(paragraphLines, blocks);
      return;
    }
    const orderedMatch = line.match(/^(?:\d+[.、]|[（(]?\d+[)）])\s*(.+)$/);
    if (orderedMatch) {
      flushParagraph(paragraphLines, blocks);
      pushListBlock(blocks, "ordered", orderedMatch[1].trim());
      return;
    }
    const unorderedMatch = line.match(/^[-*•]\s*(.+)$/);
    if (unorderedMatch) {
      flushParagraph(paragraphLines, blocks);
      pushListBlock(blocks, "unordered", unorderedMatch[1].trim());
      return;
    }
    const isShortCodeLike = /^[A-Za-z0-9_./:-]{3,}$/.test(line) && line.length <= 36;
    if (isShortCodeLike) {
      flushParagraph(paragraphLines, blocks);
      blocks.push({ type: "code", text: line });
      return;
    }
    paragraphLines.push(line);
  });
  flushParagraph(paragraphLines, blocks);
  return blocks;
}

function buildAnswerContent(finalAnswer: string, explanation?: Explanation) {
  if (finalAnswer.trim()) {
    return dedupeDisplayAnswer(stripMarkdownArtifacts(finalAnswer));
  }
  const stepContent = (explanation?.steps || [])
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
  if (stepContent) {
    return dedupeDisplayAnswer(stripMarkdownArtifacts(stepContent));
  }
  if (explanation?.topic?.trim()) {
    return `我已经围绕「${stripMarkdownArtifacts(explanation.topic)}」整理好讲解了。`;
  }
  return "";
}

function chooseDisplayAnswer(currentAnswer: string, finalAnswer: string, data: any) {
  if (!finalAnswer.trim()) return dedupeDisplayAnswer(currentAnswer);
  if (!currentAnswer.trim()) return dedupeDisplayAnswer(finalAnswer);
  const streamingMode = safeText(data?.streaming_mode || data?.streamingMode);
  const tokenCount = safeCount(data?.streaming_token_count ?? data?.streamingTokenCount) || 0;
  const currentClean = sanitizeAnswerText(currentAnswer);
  const finalClean = sanitizeAnswerText(finalAnswer);
  if ((streamingMode === "token" || tokenCount > 0) && finalClean.length < currentClean.length * 0.8) {
    return dedupeDisplayAnswer(currentAnswer);
  }
  return dedupeDisplayAnswer(finalAnswer);
}

function splitNodeReplayChunks(text: string) {
  const normalized = sanitizeAnswerText(text);
  if (!normalized) return [];
  const lines = normalized.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length > 1) {
    return lines.map((line, index) => (index < lines.length - 1 ? `${line}\n` : line));
  }
  const chunks: string[] = [];
  let current = "";
  for (const char of normalized) {
    current += char;
    if ("。！？!?\n".includes(char) && current.trim()) {
      chunks.push(current);
      current = "";
    }
  }
  if (current.trim()) chunks.push(current);
  if (chunks.length > 1) return chunks;
  return normalized.match(/[\s\S]{1,72}/g) || [normalized];
}

function webSearchStatusText(data: any) {
  const stage = safeText(data?.stream_stage);
  const hasWebSignal = stage === "web_search_if_needed"
    || data?.web_search_attempted !== undefined
    || data?.web_search_used !== undefined
    || Boolean(data?.web_search_diagnosis);
  if (!hasWebSignal) return "";

  if (data?.web_search_error || data?.status === "failed") {
    return "联网检索暂时不可用，我先基于通用知识说明。";
  }
  if (data?.web_search_used || Number(data?.doc_count || 0) > 0) {
    return "已联网参考资料整理。";
  }
  if (data?.status === "skipped" || data?.web_search_attempted === false) {
    return "";
  }
  return "我正在联网检索并整理答案。";
}

function asyncJobStatusText(data: any) {
  const stage = safeText(data?.stream_stage);
  const status = safeText(data?.status);
  const detail = safeText(data?.detail);
  if (stage === "chat_async_job_completed" || status === "completed" || /完成|ready/i.test(detail)) {
    return "答案已经整理完成。";
  }
  if (
    stage === "chat_async_job_pending" ||
    stage === "chat_async_job" ||
    status === "pending"
  ) {
    return "我正在联网检索并整理答案，稍等一下就好。";
  }
  return "";
}

function isInternalProcessText(text?: string) {
  const normalized = safeText(text);
  if (!normalized) return false;
  return /cloud_container|chunk|流式降级|未接入|真实\s*\d|节点\s*\d|notebook\s*(?:未命中|暂无|没有)|知识库策略|学习记忆|练习方向待确认|MCP|provider/i.test(normalized);
}

function readableStatus(data: any) {
  const friendly = webSearchStatusText(data) || asyncJobStatusText(data);
  if (friendly) return friendly;
  const raw = (
    qualityFailureText(data) ||
    data?.detail ||
    data?.rag_warning ||
    data?.web_search_diagnosis ||
    data?.retrieval_diagnosis ||
    data?.message ||
    data?.stage_label ||
    ""
  );
  if (!CHAT_DEBUG_PROCESS && isInternalProcessText(raw)) {
    return safeText(data?.stage_label) || "";
  }
  return raw;
}

function stringifyStatusValue(value: any): string {
  if (!value) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map(stringifyStatusValue).filter(Boolean).join("；");
  }
  if (typeof value === "object") {
    return (
      value.message ||
      value.reason ||
      value.summary ||
      value.detail ||
      value.error ||
      ""
    ).toString().trim();
  }
  return String(value).trim();
}

function quizGenerationStatus(data: any) {
  return data?.quiz_generation_status || data?.generation_status || data?.quiz_quality_report || null;
}

function qualityFailureText(data: any) {
  const status = quizGenerationStatus(data) || {};
  const errors = Array.isArray(data?.errors) ? data.errors : Array.isArray(status?.errors) ? status.errors : [];
  const explicitFailure =
    stringifyStatusValue(status?.quality_failure_summary) ||
    stringifyStatusValue(data?.quality_failure_summary) ||
    stringifyStatusValue(status?.failure_summary) ||
    stringifyStatusValue(errors);
  if (explicitFailure) return explicitFailure;

  const qualityReport = status?.quality_report || data?.quiz_quality_report || data?.quality_report || {};
  const qualityFailed = qualityReport?.passed === false || status?.quality_passed === false || status?.passed === false;
  if (qualityFailed || data?.status === "failed") {
    return stringifyStatusValue(qualityReport?.summary || qualityReport?.issues || status?.message || data?.message);
  }
  return "";
}

function repairStatusText(data: any) {
  const status = quizGenerationStatus(data) || {};
  const attemptCount = Number(status?.repair_attempt_count || data?.repair_attempt_count || 0);
  const replacedCount = Number(status?.repair_replaced_count || data?.repair_replaced_count || 0);
  const modelUsed = status?.repair_model_used || data?.repair_model_used;
  const parts: string[] = [];
  if (attemptCount > 0) parts.push(`质量门修复 ${attemptCount} 轮`);
  if (replacedCount > 0) parts.push(`替换补齐 ${replacedCount} 道题`);
  if (modelUsed) parts.push(`修复模型 ${modelUsed}`);
  return parts.join("，");
}

function quizStatusDetail(data: any, addedCount = 0, totalCount = 0) {
  const failure = qualityFailureText(data);
  const repair = repairStatusText(data);
  if (addedCount > 0) {
    return [`新增 ${addedCount} 道练习题，当前队列共 ${totalCount} 道。`, repair].filter(Boolean).join(" ");
  }
  if (totalCount > 0) {
    return [`这组练习题已在队列中，当前队列共 ${totalCount} 道。`, repair].filter(Boolean).join(" ");
  }
  if (failure) {
    return `练习题未保存：${failure}`;
  }
  return repair || "需要先选择练习方向。";
}

function statusStage(data: any): ChatProcessStage {
  const elapsed = typeof data?.elapsed === "number" ? { elapsed: data.elapsed } : {};
  if (quizGenerationStatus(data) || data?.stream_stage === "quiz_quality") {
    const failure = qualityFailureText(data);
    const repair = repairStatusText(data);
    return {
      key: "quiz_quality",
      label: "练习质量检查",
      detail: failure ? `练习题未保存：${failure}` : repair || readableStatus(data) || "已完成练习题质量检查。",
      status: failure || data?.status === "failed" ? "failed" : data?.status === "completed" ? "completed" : "running",
      ...elapsed
    };
  }
  if (data?.guard || data?.allow_tools !== undefined || data?.allow_search !== undefined) {
    return {
      key: "guard",
      label: "工具守卫",
      detail: "已确认本轮工具与搜索策略。",
      status: "completed",
      ...elapsed
    };
  }
  if (data?.web_search_attempted !== undefined || data?.web_search_diagnosis) {
    const searchStatus = webSearchStatusText(data);
    return {
      key: "web_search",
      label: "网络搜索",
      detail: searchStatus || (data?.web_search_used ? "已联网参考资料整理。" : "未使用网络搜索。"),
      status: "completed",
      ...elapsed
    };
  }
  if (data?.context_audit || data?.verified_context) {
    return {
      key: "context_audit",
      label: "上下文审查",
      detail: "已检查可用资料和证据质量。",
      status: "completed",
      ...elapsed
    };
  }
  if (data?.retrieved_docs || data?.retrieval_relevance || data?.rag_ready !== undefined) {
    return {
      key: "retrieval",
      label: "知识检索",
      detail: data?.retrieval_diagnosis || "已完成知识库检索。",
      status: "completed",
      ...elapsed
    };
  }
  if (data?.teaching_user_state || data?.teaching_input_type) {
    return {
      key: "teaching",
      label: "教学策略",
      detail: "已根据当前问题选择讲解节奏。",
      status: "completed",
      ...elapsed
    };
  }
  const fallbackLabel = data?.stage_label || (data?.heartbeat ? "处理中" : "准备中");
  const fallbackDetail = readableStatus(data);
  return {
    key: data?.stream_stage || (data?.heartbeat ? "heartbeat" : "status"),
    label: fallbackLabel,
    detail: fallbackDetail && fallbackDetail !== fallbackLabel ? fallbackDetail : "模型正在处理。",
    status: data?.status === "failed" ? "failed" : data?.status === "completed" ? "completed" : "running",
    ...elapsed
  };
}

function webSearchStageFromData(data: any): ChatProcessStage | undefined {
  const hasWebSignal = data?.web_search_attempted !== undefined
    || data?.web_search_used !== undefined
    || Boolean(data?.web_search_error)
    || Boolean(data?.web_search_diagnosis);
  if (!hasWebSignal) return undefined;
  const searchStatus = webSearchStatusText(data);
  return {
    key: "web_search",
    label: "网络搜索",
    detail: searchStatus || (data?.web_search_used ? "已联网参考资料整理。" : "未使用网络搜索。"),
    status: data?.web_search_error || data?.status === "failed" ? "failed" : "completed",
    ...(typeof data?.elapsed === "number" ? { elapsed: data.elapsed } : {})
  };
}

function streamTransportLabel(transport?: string) {
  const normalized = safeText(transport);
  if (normalized === "chunked") return "chunked 流式";
  if (normalized === "cloud_container_sync") return "云托管同步";
  if (normalized === "sync_fallback") return "同步请求";
  return normalized || "传输状态";
}

function streamDiagnosticsDetail(diagnostics: ChatStreamDiagnostics) {
  const parts = [
    streamTransportLabel(diagnostics.transport),
    diagnostics.chunkSupported === false ? "未接入 chunk" : diagnostics.chunkSupported ? "已接入 chunk" : "",
    typeof diagnostics.chunkCount === "number" ? `chunk ${diagnostics.chunkCount}` : "",
    typeof diagnostics.parsedEventCount === "number" ? `事件 ${diagnostics.parsedEventCount}` : "",
    typeof diagnostics.realTokenDeltaCount === "number" ? `真实 ${diagnostics.realTokenDeltaCount}` : "",
    typeof diagnostics.syntheticDeltaCount === "number" ? `节点 ${diagnostics.syntheticDeltaCount}` : "",
    typeof diagnostics.firstChunkMs === "number" ? `首包 ${diagnostics.firstChunkMs}ms` : "",
    typeof diagnostics.firstRealTokenDeltaMs === "number" ? `首个真实片段 ${diagnostics.firstRealTokenDeltaMs}ms` : ""
  ].filter(Boolean);
  const degraded = streamingDegradedText(diagnostics.degradedReason);
  const detail = safeText(diagnostics.detail);
  return [parts.join(" · "), degraded || detail].filter(Boolean).join("。");
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(STARTER_MESSAGES);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [statusText, setStatusText] = useState("");
  const [streamStages, setStreamStages] = useState<ChatProcessStage[]>([]);
  const [streamQuiz, setStreamQuiz] = useState<QuizItem[]>([]);
  const [streamClarification, setStreamClarification] = useState<QuizClarificationPanel | null>(null);
  const [streamPresentation, setStreamPresentation] = useState<StreamPresentation>({
    deltaCount: 0,
    synthetic: false,
    active: false
  });
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState(DEFAULT_NOTEBOOK_ID);
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [sessionId, setSessionId] = useState("");
  // History drawer
  const [showHistory, setShowHistory] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  // Model health
  const [modelStatus, setModelStatus] = useState<"idle" | "checking" | "ok" | "error">("idle");
  const [modelName, setModelName] = useState("");
  const [openProcessKeys, setOpenProcessKeys] = useState<Record<string, boolean>>({});
  const streamTaskRef = useRef<{ abort: () => void } | null>(null);
  const nodeReplayTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const nodeReplayQueueRef = useRef<string[]>([]);
  const pendingFinalizeRef = useRef(false);
  const completedAnswerEventKeyRef = useRef("");
  const hasRealTokenDeltaRef = useRef(false);
  const streamPresentationRef = useRef<StreamPresentation>({
    deltaCount: 0,
    synthetic: false,
    active: false
  });
  const answerRef = useRef("");
  const explanationRef = useRef<Explanation | undefined>();
  const quizRef = useRef<QuizItem[]>([]);
  const quizRequestRef = useRef<QuizRequestResolution | undefined>();
  const quizClarificationRef = useRef<QuizClarificationPanel | undefined>();
  const stagesRef = useRef<ChatProcessStage[]>([]);
  const reasoningRef = useRef("");
  const routeRef = useRef("");
  const questionTypeRef = useRef("");
  const processMetaRef = useRef<{
    currentStage?: string;
    reasoningSummary?: string;
    execution?: ChatProcessExecution;
    streamDiagnostics?: ChatStreamDiagnostics;
    toolCalls: ChatProcessToolCall[];
  }>({ toolCalls: [] });

  const selectedNotebook = useMemo(
    () => notebooks.find((item) => item.id === selectedNotebookId),
    [notebooks, selectedNotebookId]
  );

  useDidShow(() => {
    void bootstrapChat();
  });

  async function bootstrapChat() {
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    setLearningStoreUser(user.id);
    setSelectedNotebookId(getStoredNotebookId());
    setSessionId(getStoredSessionId());
    const draft = getChatDraft();
    if (draft.length > 0) {
      setMessages(draft);
    }
    await loadNotebooks();
    checkModelHealth();
  }

  useEffect(() => {
    if (messages.length > 0) {
      setChatDraft(messages);
    }
  }, [messages]);

  useUnload(() => {
    clearNodeReplayTimer();
    streamTaskRef.current?.abort();
  });

  async function loadNotebooks() {
    try {
      const list = await fetchNotebooks();
      setNotebooks(list);
      const stored = getStoredNotebookId();
      const current = list.find((item) => item.id === stored) || list[0];
      if (current) {
        setSelectedNotebookId(current.id);
        setStoredNotebookId(current.id);
      }
    } catch {
      setNotebooks([]);
    }
  }

  function checkModelHealth() {
    setModelStatus("checking");
    fetchModelHealth()
      .then((result) => {
        setModelStatus(result.chat_model_ok ? "ok" : "error");
        if (result.chat_model) setModelName(result.chat_model);
      })
      .catch(() => setModelStatus("error"));
  }

  async function loadSessions() {
    const user = requireAuthUser();
    if (!user) return;
    setSessionsLoading(true);
    try {
      const list = await fetchSessions(user.id);
      setSessions(list);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }

  function handleOpenHistory() {
    setShowHistory(true);
    void loadSessions();
  }

  function handleSelectSession(session: ChatSession) {
    setShowHistory(false);
    setSessionId(session.id);
    setStoredSessionId(session.id);
    clearChatDraft();
    setMessages([{
      role: "assistant",
      content: `已切换到会话「${session.title}」，继续上次的对话。`,
      timestamp: Date.now()
    }]);
  }

  async function handleDeleteSession(sid: string) {
    const user = requireAuthUser();
    if (!user) return;
    try {
      await deleteSession(user.id, sid);
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      Taro.showToast({ title: "已删除", icon: "success" });
    } catch {
      Taro.showToast({ title: "删除失败", icon: "none" });
    }
  }

  function setStreamPresentationState(next: StreamPresentation | ((current: StreamPresentation) => StreamPresentation)) {
    setStreamPresentation((current) => {
      const value = typeof next === "function" ? next(current) : next;
      streamPresentationRef.current = value;
      return value;
    });
  }

  function clearNodeReplayTimer() {
    if (nodeReplayTimerRef.current) {
      clearInterval(nodeReplayTimerRef.current);
      nodeReplayTimerRef.current = null;
    }
  }

  function finishPendingFinalizeIfReady() {
    if (!pendingFinalizeRef.current || nodeReplayTimerRef.current || nodeReplayQueueRef.current.length > 0) return;
    pendingFinalizeRef.current = false;
    finalizeAssistantMessage(answerRef.current);
  }

  function startNodeReplay() {
    if (nodeReplayTimerRef.current) return;
    nodeReplayTimerRef.current = setInterval(() => {
      const next = nodeReplayQueueRef.current.shift();
      if (!next) {
        clearNodeReplayTimer();
        setStreamPresentationState((current) => ({ ...current, active: false }));
        finishPendingFinalizeIfReady();
        return;
      }
      answerRef.current += next;
      setStreamText(answerRef.current);
      setStreamPresentationState((current) => ({
        mode: "node",
        synthetic: true,
        deltaCount: current.deltaCount + 1,
        active: true
      }));
      setStatusText("正在展示模型回答");
    }, NODE_REPLAY_INTERVAL_MS);
  }

  function enqueueNodeReplay(text: string, replace = false) {
    const chunks = splitNodeReplayChunks(text);
    if (!chunks.length) return;
    if (replace) {
      answerRef.current = "";
      setStreamText("");
      nodeReplayQueueRef.current = [];
    }
    nodeReplayQueueRef.current.push(...chunks);
    setStreamPresentationState((current) => ({
      mode: "node",
      synthetic: true,
      deltaCount: current.deltaCount,
      active: true
    }));
    startNodeReplay();
  }

  function resetStreamRefs() {
    clearNodeReplayTimer();
    nodeReplayQueueRef.current = [];
    pendingFinalizeRef.current = false;
    completedAnswerEventKeyRef.current = "";
    hasRealTokenDeltaRef.current = false;
    streamPresentationRef.current = { deltaCount: 0, synthetic: false, active: false };
    answerRef.current = "";
    explanationRef.current = undefined;
    quizRef.current = [];
    quizRequestRef.current = undefined;
    quizClarificationRef.current = undefined;
    stagesRef.current = [];
    reasoningRef.current = "";
    routeRef.current = "";
    questionTypeRef.current = "";
    processMetaRef.current = { toolCalls: [] };
    setStreamQuiz([]);
    setStreamClarification(null);
    setStreamStages([]);
    setStreamPresentation({ deltaCount: 0, synthetic: false, active: false });
  }

  function upsertStage(stage: ChatProcessStage, options: { setCurrentStage?: boolean } = {}) {
    const next = [...stagesRef.current.filter((item) => item.key !== stage.key), stage].slice(-8);
    stagesRef.current = next;
    if (options.setCurrentStage !== false) {
      processMetaRef.current.currentStage = stage.label;
    }
    setStreamStages(next);
  }

  function mergeCurrentToolCalls(toolCalls: ChatProcessToolCall[]) {
    if (!toolCalls.length) return;
    processMetaRef.current.toolCalls = mergeProcessToolCalls(
      processMetaRef.current.toolCalls,
      toolCalls
    );
  }

  function updateStreamDiagnostics(raw: any) {
    if (!raw || typeof raw !== "object") return;
    const current = processMetaRef.current.streamDiagnostics || {};
    const next: ChatStreamDiagnostics = {
      ...current,
      ...raw,
      degradedReason: safeText(raw.degradedReason || raw.streaming_degraded_reason || current.degradedReason),
      detail: safeText(raw.detail) || current.detail
    };
    processMetaRef.current.streamDiagnostics = next;
    if (next.transport === "sync_fallback") {
      setStreamPresentationState((currentPresentation) => ({
        ...currentPresentation,
        mode: "node",
        synthetic: true,
        active: true
      }));
    }
    upsertStage({
      key: "stream_transport",
      label: CHAT_DEBUG_PROCESS ? "流式传输" : "云托管同步",
      detail: streamDiagnosticsDetail(next),
      status: /error|异常|失败/.test(`${next.degradedReason || ""} ${next.detail || ""}`)
        ? "failed"
        : next.transport === "sync_fallback"
          || (next.transport === "cloud_container_sync" && (next.parsedEventCount || 0) > 0)
          || (next.realTokenDeltaCount || 0) > 0
            ? "completed"
            : "running"
    }, {
      setCurrentStage: false
    });
  }

  function buildProcessSnapshot(stages: ChatProcessStage[] = stagesRef.current): ChatProcess | undefined {
    if (!CHAT_DEBUG_PROCESS) return undefined;
    const meta = processMetaRef.current;
    const reasoningSummary = meta.reasoningSummary
      || (reasoningRef.current ? `已接收 ${reasoningRef.current.length} 字模型思考过程，移动端仅保留安全摘要。` : "");
    const hasProcess = stages.length > 0
      || Boolean(reasoningSummary)
      || Boolean(meta.execution)
      || Boolean(meta.streamDiagnostics)
      || meta.toolCalls.length > 0;
    if (!hasProcess) return undefined;
    return {
      currentStage: meta.currentStage || stages[stages.length - 1]?.label,
      stages: [...stages],
      reasoningSummary: reasoningSummary || undefined,
      execution: meta.execution,
      streamDiagnostics: meta.streamDiagnostics,
      toolCalls: meta.toolCalls.length ? [...meta.toolCalls] : undefined
    };
  }

  function finalizeAssistantMessage(content: string, isError = false) {
    const fallback = quizRef.current.length
      ? "我顺手帮你准备了一组练习题，去刷题页就能接着做。"
      : quizClarificationRef.current
        ? "我可以帮你出题，但需要先确定练习方向。"
        : "本轮没有返回内容，请稍后重试。";
    const text = dedupeDisplayAnswer(content).trim() || fallback;
    const process = buildProcessSnapshot();
    setMessages((current) => [
      ...current,
      {
        role: "assistant",
        content: text,
        timestamp: Date.now(),
        isError,
        quiz: quizRef.current.length ? quizRef.current : undefined,
        quizRequest: quizRequestRef.current,
        quizClarification: quizClarificationRef.current,
        explanation: explanationRef.current,
        process,
        questionType: questionTypeRef.current || undefined,
        route: routeRef.current || undefined
      }
    ]);
    resetStreamRefs();
    setStreamText("");
    setStatusText("");
    setIsStreaming(false);
    streamTaskRef.current = null;
  }

  function finalizeAfterReplay() {
    if (nodeReplayTimerRef.current || nodeReplayQueueRef.current.length > 0) {
      pendingFinalizeRef.current = true;
      return;
    }
    finalizeAssistantMessage(answerRef.current);
  }

  function handleStreamEvent(eventName: string, data: any) {
    if (eventName === "stream_diagnostics") {
      updateStreamDiagnostics(data);
      return;
    }

    if (eventName === "status") {
      const message = readableStatus(data);
      if (message) setStatusText(message);
      mergeCurrentToolCalls(mergeToolCalls(data?.tool_calls, data?.external_tool_calls));
      upsertStage(statusStage(data));
      return;
    }

    if (eventName === "routing") {
      routeRef.current = data?.route || routeRef.current;
      questionTypeRef.current = data?.question_type || questionTypeRef.current;
      const routeText = CHAT_DEBUG_PROCESS && data?.route ? `已选择路线：${data.route}` : "正在理解问题";
      setStatusText(routeText);
      upsertStage({
        key: "routing",
        label: "问题识别",
        detail: routeText,
        status: "completed"
      });
      return;
    }

    if (eventName === "reasoning_delta") {
      const delta = data?.delta || "";
      if (delta) {
        reasoningRef.current += delta;
        setStatusText(CHAT_DEBUG_PROCESS ? `模型思考中：已接收 ${reasoningRef.current.length} 字` : "正在整理回答");
        upsertStage({
          key: "reasoning",
          label: "模型思考",
          detail: "正在接收模型思考过程，移动端仅显示摘要。",
          status: "running"
        });
      }
      return;
    }

    if (eventName === "answer_delta") {
      const delta = data?.delta || "";
      if (delta) {
        const mode = safeText(data?.streaming_mode) || "token";
        const synthetic = Boolean(data?.is_synthetic_delta);
        if (mode === "token" && !synthetic) {
          hasRealTokenDeltaRef.current = true;
          clearNodeReplayTimer();
          nodeReplayQueueRef.current = [];
          answerRef.current += delta;
          setStreamText(answerRef.current);
          setStreamPresentationState((current) => ({
            mode,
            synthetic,
            deltaCount: current.deltaCount + 1,
            active: true
          }));
          setStatusText("正在实时生成回答");
        } else {
          enqueueNodeReplay(delta);
          setStatusText("正在展示模型回答");
        }
        upsertStage({
          key: "answer_stream",
          label: "正在生成回答",
          detail: mode === "token" && !synthetic ? "回答正文正在实时流式输出。" : "回答正文按节点完成进度分段展示。",
          status: "running"
        });
      }
      return;
    }

    if (eventName === "explanation" || eventName === "final") {
      const explanation = data?.explanation as Explanation | undefined;
      const finalAnswer = buildAnswerContent(data?.final_answer || "", explanation);
      const completedAnswerKey = [safeText(data?.job_id), safeText(data?.request_id)]
        .filter(Boolean)
        .join("|");
      if (finalAnswer && completedAnswerKey && completedAnswerEventKeyRef.current === completedAnswerKey) {
        return;
      }
      const reasoningSummary = safeText(data?.reasoning_summary);
      const toolCalls = mergeToolCalls(data?.tool_calls, data?.external_tool_calls);
      const execution = buildExecutionInfo(data);
      const webSearchStage = webSearchStageFromData(data);
      const toolDecisionRounds = Array.isArray(data?.tool_decision_rounds)
        ? data.tool_decision_rounds
        : [];
      explanationRef.current = explanation || explanationRef.current;
      routeRef.current = data?.route || routeRef.current;
      questionTypeRef.current = data?.question_type || questionTypeRef.current;
      if (reasoningSummary) {
        processMetaRef.current.reasoningSummary = reasoningSummary;
      }
      mergeCurrentToolCalls(toolCalls);
      if (webSearchStage) {
        upsertStage(webSearchStage);
      }
      if (toolDecisionRounds.length > 0) {
        const usedToolCount = toolDecisionRounds.filter((item: any) => {
          const tool = safeText(item?.tool || item?.capability || item?.name);
          return tool && tool !== "none";
        }).length;
        upsertStage({
          key: "tool_decision",
          label: "工具决策",
          detail: usedToolCount > 0
            ? `模型完成 ${toolDecisionRounds.length} 轮工具判断，调用了 ${usedToolCount} 次工具。`
            : `模型完成 ${toolDecisionRounds.length} 轮工具判断，决定直接回答。`,
          status: "completed",
          ...(typeof data?.elapsed === "number" ? { elapsed: data.elapsed } : {})
        });
      }
      if (execution) {
        processMetaRef.current.execution = execution;
        if (execution.streamingDegradedReason) {
          updateStreamDiagnostics({
            degradedReason: execution.streamingDegradedReason,
            detail: streamingDegradedText(execution.streamingDegradedReason)
          });
        }
        setStreamPresentationState((current) => ({
          mode: execution.streamingMode || current.mode,
          synthetic: current.synthetic,
          deltaCount: execution.streamingTokenCount || current.deltaCount,
          active: Boolean(nodeReplayTimerRef.current || nodeReplayQueueRef.current.length > 0)
        }));
        upsertStage({
          key: "execution",
          label: "模型执行",
          detail: [
            callStatusLabel(execution.callStatus),
            execution.mode,
            execution.modelFamily,
            execution.modelId,
            execution.streamingMode === "token" ? "逐字流式" : execution.streamingMode === "node" ? "节点级流式" : "",
            typeof execution.streamingTokenCount === "number" && execution.streamingTokenCount > 0 ? `流式 ${execution.streamingTokenCount} 段` : "",
            typeof execution.modelLatencyMs === "number" && execution.modelLatencyMs > 0 ? `${execution.modelLatencyMs}ms` : "",
            execution.modelAttempts?.length ? `尝试 ${execution.modelAttempts.length} 次` : "",
            execution.degraded ? "已降级回退" : ""
          ].filter(Boolean).join(" · ") || "模型调用已完成。",
          status: "completed",
          ...(typeof data?.elapsed === "number" ? { elapsed: data.elapsed } : {})
        });
      }
      if (finalAnswer) {
        if (completedAnswerKey) {
          completedAnswerEventKeyRef.current = completedAnswerKey;
        }
        if (hasRealTokenDeltaRef.current) {
          const displayAnswer = chooseDisplayAnswer(answerRef.current, finalAnswer, data);
          answerRef.current = displayAnswer;
          setStreamText(displayAnswer);
          setStreamPresentationState((current) => ({ ...current, active: false }));
        } else if (!answerRef.current.trim() && nodeReplayQueueRef.current.length === 0) {
          enqueueNodeReplay(finalAnswer, true);
        }
      }
      setStatusText("正在整理回答");
      upsertStage({
        key: "answer",
        label: "已生成回答",
        detail: finalAnswer ? "最终回答已经准备好。" : "结构化讲解已经准备好。",
        status: "completed",
        ...(typeof data?.elapsed === "number" ? { elapsed: data.elapsed } : {})
      });
      return;
    }

    if (eventName === "quiz") {
      const quizItems = Array.isArray(data?.quiz_items) ? data.quiz_items : [];
      const quizRequest = data?.quiz_request as QuizRequestResolution | undefined;
      const quizClarification = data?.quiz_clarification as QuizClarificationPanel | undefined;
      const finalAnswer = buildAnswerContent(data?.final_answer || "", undefined);
      quizRequestRef.current = quizRequest || quizRequestRef.current;
      quizClarificationRef.current = quizClarification || quizClarificationRef.current;
      setStreamClarification(quizClarification || null);
      let addedCount = 0;
      let totalCount = 0;
      if (quizItems.length > 0) {
        quizRef.current = quizItems;
        setStreamQuiz(quizItems);
        const appendResult = appendStoredQuiz(quizItems, {
          sessionId: data?.session_id || sessionId || getStoredSessionId(),
          subjectId: quizRequest?.subject_id || data?.subject_id || selectedNotebookId || DEFAULT_NOTEBOOK_ID
        });
        addedCount = appendResult.addedCount;
        totalCount = appendResult.totalCount;
        setStatusText(addedCount > 0 ? `已新增 ${addedCount} 道练习题` : "这组练习题已在队列中");
      }
      if (finalAnswer) {
        answerRef.current = dedupeDisplayAnswer(finalAnswer);
        setStreamText(answerRef.current);
      } else if (quizClarification) {
        answerRef.current = "我可以帮你出题，但需要先确定练习方向。";
        setStreamText(answerRef.current);
      } else if (!quizItems.length && qualityFailureText(data)) {
        answerRef.current = quizStatusDetail(data);
        setStreamText(answerRef.current);
      }
      const detail = quizStatusDetail(data, addedCount, totalCount);
      upsertStage({
        key: "quiz",
        label: quizItems.length ? "练习题已准备" : quizClarification ? "练习方向待确认" : "练习题未保存",
        detail,
        status: quizItems.length || quizClarification ? "completed" : "failed"
      });
      return;
    }

    if (eventName === "memory") {
      if (data?.memory) {
        setStoredMemory(data.memory);
      }
      upsertStage({
        key: "memory",
        label: "学习记忆",
        detail: "本轮学习记忆已更新。",
        status: "completed"
      });
    }
  }

  // Notebook switcher removed per user request

  async function sendQuestion(rawQuestion: string) {
    const question = rawQuestion.trim();
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user || !question || isStreaming) return;
    setLearningStoreUser(user.id);

    const nextSessionId = sessionId || createSessionId();
    const allowWebForRequest = webSearchEnabled;
    setSessionId(nextSessionId);
    setStoredSessionId(nextSessionId);
    resetStreamRefs();

    setMessages((current) => [
      ...current,
      { role: "user", content: question, timestamp: Date.now() }
    ]);
    setInputValue("");
    setStreamText("");
    setStatusText(allowWebForRequest ? "联网搜索已开启，正在接入模型" : "正在接入模型");
    setIsStreaming(true);

    streamTaskRef.current = sendChatStream(
      buildChatStreamPayload({
        user_id: user.id,
        session_id: nextSessionId,
        question,
        subject_id: selectedNotebookId || DEFAULT_NOTEBOOK_ID,
        thinking_mode: false,
        allow_web: allowWebForRequest
      }),
      {
        onEvent: ({ event, data }) => handleStreamEvent(event, data),
        onDone: finalizeAfterReplay,
        onError: (error) => finalizeAssistantMessage(error.message || "聊天连接中断", true)
      }
    );
  }

  function handleSend() {
    void sendQuestion(inputValue);
  }

  function toggleWebSearch() {
    if (isStreaming) return;
    setWebSearchEnabled((current) => !current);
  }

  function handleNewChat() {
    streamTaskRef.current?.abort();
    clearStoredSessionId();
    clearChatDraft();
    setSessionId("");
    setMessages(STARTER_MESSAGES);
    setStreamText("");
    setStatusText("");
    setIsStreaming(false);
    setOpenProcessKeys({});
    resetStreamRefs();
  }

  function toggleProcessPanel(key: string) {
    setOpenProcessKeys((current) => ({
      ...current,
      [key]: !current[key]
    }));
  }

  function renderStageList(stages: ChatProcessStage[] | undefined) {
    if (!stages?.length) return null;
    return (
      <View className="process-list">
        {stages.map((stage) => (
          <View key={stage.key} className={`process-item ${stage.status}`}>
            <View className="process-item-head">
              <Text className="process-label">{stage.label}</Text>
              {typeof stage.elapsed === "number" ? (
                <Text className="process-elapsed">{stage.elapsed.toFixed(2)}s</Text>
              ) : null}
            </View>
            <Text className="process-detail">{stage.detail}</Text>
          </View>
        ))}
      </View>
    );
  }

  function renderExecution(execution: ChatProcessExecution | undefined) {
    if (!execution) return null;
    const attempts = execution.modelAttempts || [];
    const successCount = attempts.filter((item) => safeText(item.status).toLowerCase() === "ok").length;
    const tags = [
      callStatusLabel(execution.callStatus),
      execution.mode,
      execution.modelFamily,
      execution.modelProvider,
      execution.modelId,
      execution.streamingMode === "token" ? "逐字流式" : execution.streamingMode === "node" ? "节点级流式" : "",
      typeof execution.streamingTokenCount === "number" && execution.streamingTokenCount > 0 ? `流式 ${execution.streamingTokenCount} 段` : "",
      execution.streamingDegradedReason ? "流式降级" : "",
      typeof execution.modelLatencyMs === "number" && execution.modelLatencyMs > 0 ? `${execution.modelLatencyMs}ms` : "",
      attempts.length ? `尝试 ${attempts.length} 次` : "",
      execution.degraded ? "已降级" : ""
    ].filter(Boolean);
    return (
      <View className="process-section">
        <Text className="process-section-title">模型执行</Text>
        <View className="process-tags">
          {tags.map((tag) => (
            <Text key={`${tag}`} className="process-tag">{tag}</Text>
          ))}
        </View>
        {execution.fallbackUsed ? (
          <Text className="process-note">
            主模型 {execution.primaryModelId || "当前主模型"} 不可用，已使用 {execution.fallbackModelId || execution.modelId || "备用模型"} 完成本轮回答。
          </Text>
        ) : null}
        {attempts.length ? (
          <Text className="process-note">
            模型尝试：{successCount > 0 ? `${successCount} 次成功` : "暂无成功标记"}，最近一次状态 {safeText(attempts[attempts.length - 1]?.status) || "unknown"}。
          </Text>
        ) : null}
        {execution.streamingDegradedReason ? (
          <Text className="process-note">{streamingDegradedText(execution.streamingDegradedReason)}</Text>
        ) : null}
      </View>
    );
  }

  function renderStreamDiagnostics(diagnostics: ChatStreamDiagnostics | undefined) {
    if (!diagnostics) return null;
    const tags = [
      streamTransportLabel(diagnostics.transport),
      diagnostics.chunkSupported === false ? "未接入 chunk" : diagnostics.chunkSupported ? "已接入 chunk" : "",
      typeof diagnostics.chunkCount === "number" ? `chunk ${diagnostics.chunkCount}` : "",
      typeof diagnostics.parsedEventCount === "number" ? `事件 ${diagnostics.parsedEventCount}` : "",
      typeof diagnostics.realTokenDeltaCount === "number" ? `真实 ${diagnostics.realTokenDeltaCount}` : "",
      typeof diagnostics.syntheticDeltaCount === "number" ? `节点 ${diagnostics.syntheticDeltaCount}` : "",
      typeof diagnostics.firstChunkMs === "number" ? `首包 ${diagnostics.firstChunkMs}ms` : "",
      typeof diagnostics.firstRealTokenDeltaMs === "number" ? `首个真实片段 ${diagnostics.firstRealTokenDeltaMs}ms` : ""
    ].filter(Boolean);
    const degraded = streamingDegradedText(diagnostics.degradedReason);
    return (
      <View className="process-section">
        <Text className="process-section-title">传输诊断</Text>
        <View className="process-tags">
          {tags.map((tag) => (
            <Text key={`${tag}`} className="process-tag">{tag}</Text>
          ))}
        </View>
        {degraded || diagnostics.detail ? (
          <Text className="process-note">{degraded || diagnostics.detail}</Text>
        ) : null}
      </View>
    );
  }

  function processSummaryDetail(process: ChatProcess, stages: ChatProcessStage[], toolCalls: ChatProcessToolCall[]) {
    const execution = process.execution;
    const diagnostics = process.streamDiagnostics;
    if (!execution) {
      const transport = diagnostics ? streamTransportLabel(diagnostics.transport) : "";
      return [transport, `${stages.length} 个阶段`, `${toolCalls.length} 次工具调用`].filter(Boolean).join(" · ");
    }
    const model = execution.modelId || execution.primaryModelId || execution.modelFamily || "当前模型";
    const realDeltaCount = diagnostics?.realTokenDeltaCount || 0;
    const syntheticDeltaCount = diagnostics?.syntheticDeltaCount || 0;
    const parts = [
      callStatusLabel(execution.callStatus),
      model,
      realDeltaCount > 0
        ? `实时流式 ${realDeltaCount} 段`
        : typeof execution.streamingTokenCount === "number" && execution.streamingTokenCount > 0
          ? `流式 ${execution.streamingTokenCount} 段`
          : syntheticDeltaCount > 0
            ? `节点级更新 ${syntheticDeltaCount} 段`
            : "",
      typeof execution.modelLatencyMs === "number" && execution.modelLatencyMs > 0 ? `${execution.modelLatencyMs}ms` : "",
      toolCalls.length > 0 ? `${toolCalls.length} 次工具调用` : "0 次工具调用"
    ].filter(Boolean);
    return parts.join(" · ");
  }

  function renderToolCalls(toolCalls: ChatProcessToolCall[] | undefined) {
    if (!toolCalls?.length) return null;
    return (
      <View className="process-section">
        <Text className="process-section-title">工具调用</Text>
        {toolCalls.map((toolCall, index) => (
          <View key={`${toolCall.name}-${index}`} className="tool-call-card">
            <View className="tool-call-head">
              <Text className="tool-call-name">{toolCall.label}</Text>
              <Text className={`tool-call-status ${toolCall.success ? "success" : "failed"}`}>
                {toolCall.success ? "成功" : "失败"}
              </Text>
            </View>
            <Text className="tool-call-args">{toolCall.argsSummary || "无额外参数"}</Text>
            {typeof toolCall.docCount === "number" ? (
              <Text className="tool-call-meta">命中 {toolCall.docCount} 条</Text>
            ) : null}
            {toolCall.error ? <Text className="tool-call-error">错误：{toolCall.error}</Text> : null}
          </View>
        ))}
      </View>
    );
  }

  function renderAnswerBlocks(content: string) {
    const blocks = answerBlocks(content);
    if (!blocks.length) return <Text className="answer-paragraph">模型正在处理...</Text>;
    return blocks.map((block, blockIndex) => {
      if (block.type === "heading") {
        return <Text key={`heading-${blockIndex}`} className="answer-heading">{block.text}</Text>;
      }
      if (block.type === "code") {
        return <Text key={`code-${blockIndex}`} className="answer-code">{block.text}</Text>;
      }
      if (block.type === "paragraph") {
        return <Text key={`paragraph-${blockIndex}`} className="answer-paragraph">{block.text}</Text>;
      }
      const listBlock = block as Extract<AnswerBlock, { type: "ordered" | "unordered" }>;
      return (
        <View key={`${block.type}-${blockIndex}`} className="answer-list">
          {listBlock.items.map((item, itemIndex) => (
            <View key={`${block.type}-${blockIndex}-${itemIndex}`} className="answer-list-item">
              <Text className="answer-list-marker">
                {block.type === "ordered" ? `${itemIndex + 1}.` : "•"}
              </Text>
              <Text className="answer-list-text">{item}</Text>
            </View>
          ))}
        </View>
      );
    });
  }

  function streamStatusLabel(presentation: StreamPresentation) {
    if (!CHAT_DEBUG_PROCESS) {
      if (presentation.mode === "token" && !presentation.synthetic) return "正在生成";
      if (presentation.mode === "node" || presentation.synthetic) return "云托管同步";
      return presentation.active ? "正在整理" : "";
    }
    if (presentation.mode === "token" && !presentation.synthetic) {
      return presentation.deltaCount > 0 ? `实时流式 · ${presentation.deltaCount} 段` : "实时流式";
    }
    if (presentation.mode === "node" || presentation.synthetic) {
      return presentation.deltaCount > 0 ? `节点级更新 · ${presentation.deltaCount} 段` : "节点级更新";
    }
    return presentation.active ? "正在生成" : "";
  }

  function renderAnswerContent(
    content: string,
    options: { streaming?: boolean; presentation?: StreamPresentation } = {}
  ) {
    const label = options.presentation ? streamStatusLabel(options.presentation) : "";
    return (
      <View className={`answer-renderer ${options.streaming ? "is-streaming" : ""}`}>
        {label ? (
          <View className="answer-stream-status">
            <View className="answer-stream-dot" />
            <Text className="answer-stream-label">{label}</Text>
          </View>
        ) : null}
        {renderAnswerBlocks(content)}
        {options.streaming && options.presentation?.active && options.presentation.mode === "token" && !options.presentation.synthetic ? (
          <Text className="answer-cursor">|</Text>
        ) : null}
      </View>
    );
  }

  function renderProcessPanel(process: ChatProcess | undefined, panelKey: string) {
    if (!CHAT_DEBUG_PROCESS) return null;
    if (!process) return null;
    const stages = process.stages || [];
    const toolCalls = process.toolCalls || [];
    const isOpen = Boolean(openProcessKeys[panelKey]);
    const summary = process.currentStage || stages[stages.length - 1]?.label || "过程摘要";
    return (
      <View className="process-panel">
        <View className="process-summary" onClick={() => toggleProcessPanel(panelKey)}>
          <View className="process-summary-main">
            <Text className="process-summary-title">处理过程</Text>
            <Text className="process-summary-detail">
              {processSummaryDetail(process, stages, toolCalls)}
            </Text>
          </View>
          <View className="process-summary-side">
            <Text className="process-summary-badge">{summary}</Text>
            <Text className="process-toggle">{isOpen ? "收起" : "展开"}</Text>
          </View>
        </View>
        {isOpen ? (
          <View className="process-body">
            {renderStageList(stages)}
            {renderExecution(process.execution)}
            {renderStreamDiagnostics(process.streamDiagnostics)}
            {renderToolCalls(toolCalls)}
            {process.reasoningSummary ? (
              <View className="process-section">
                <Text className="process-section-title">决策摘要</Text>
                <Text className="process-note">{process.reasoningSummary}</Text>
              </View>
            ) : null}
          </View>
        ) : null}
      </View>
    );
  }

  function renderClarification(panel: QuizClarificationPanel | null | undefined) {
    if (!panel) return null;
    return (
      <View className="quiz-clarification">
        <Text className="quiz-card-title">{panel.title || "想练哪一块？"}</Text>
        <Text className="quiz-card-desc">{panel.description || "先选一个练习方向，我再帮你生成题包。"}</Text>
        {(panel.recommended_options || []).slice(0, 3).map((option) => (
          <Button
            key={`${option.source}-${option.value}`}
            className="button-secondary suggestion-button"
            disabled={isStreaming}
            onClick={() => void sendQuestion(`围绕 ${option.value} 出 5 道单选题`)}
          >
            {option.label || option.value}
          </Button>
        ))}
        {panel.custom_input_placeholder ? (
          <Button
            className="button-secondary suggestion-button"
            disabled={isStreaming}
            onClick={() => void sendQuestion(panel.custom_input_placeholder)}
          >
            {panel.custom_input_placeholder}
          </Button>
        ) : null}
      </View>
    );
  }

  function renderQuizPreview(quiz: QuizItem[] | undefined) {
    if (!quiz?.length) return null;
    return (
      <View className="quiz-preview">
        <View className="quiz-preview-header">
          <View>
            <Text className="quiz-card-title">练习题已经打包好了</Text>
            <Text className="quiz-card-desc">共 {quiz.length} 道题，进入刷题页继续。</Text>
          </View>
          <Button className="button-secondary quiz-link-button" onClick={() => Taro.switchTab({ url: "/pages/practice/index" })}>
            去刷题
          </Button>
        </View>
        {quiz.slice(0, 3).map((item, index) => (
          <View key={`${item.question_id || item.question}-${index}`} className="quiz-preview-item">
            <Text className="quiz-preview-meta">{item.difficulty || "练习"} · {item.knowledge_point || item.concept_name || "综合"}</Text>
            <Text className="quiz-preview-question">{item.question}</Text>
          </View>
        ))}
      </View>
    );
  }

  const modelDotClass = modelStatus === "ok" ? "dot-ok" : modelStatus === "error" ? "dot-error" : "dot-idle";

  function formatDate(ts: number) {
    const d = new Date(ts);
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  return (
    <View className="chat-page">
      <View className="chat-header">
        <View className="header-left" data-notebook-name={selectedNotebook?.name || "默认知识库"}>
          <View className="title-row">
            <Text className="page-title">问答</Text>
            <View className={`model-dot ${modelDotClass}`} onClick={checkModelHealth} />
            {modelName ? <Text className="model-name">{modelName}</Text> : null}
          </View>
        </View>
        <View className="header-actions">
          <Button className="button-secondary header-button" onClick={handleOpenHistory}>
            历史
          </Button>
          <Button className="button-secondary header-button" onClick={handleNewChat}>
            新对话
          </Button>
        </View>
      </View>

      <ScrollView className="message-list" scrollY scrollIntoView="chat-bottom">
        <View className="message-list-inner">
          {messages.map((message, index) => (
            <View key={`${message.timestamp}-${index}`} className={`message-row ${message.role}`}>
              <View className={`message-bubble ${message.isError ? "error" : ""}`}>
                <Text className="message-role">{message.role === "user" ? "你" : "Coach"}</Text>
                {message.role === "assistant" ? (
                  renderAnswerContent(message.content)
                ) : (
                  <Text className="message-content">{message.content}</Text>
                )}
                {renderClarification(message.quizClarification)}
                {renderQuizPreview(message.quiz)}
                {message.role === "assistant"
                  ? renderProcessPanel(message.process, `message-${message.timestamp}-${index}`)
                  : null}
              </View>
            </View>
          ))}
          {isStreaming ? (
            <View className="message-row assistant">
              <View className="message-bubble streaming">
                <Text className="message-role">{statusText || "正在生成"}</Text>
                {renderAnswerContent(streamText || "模型正在处理...", {
                  streaming: true,
                  presentation: streamPresentation
                })}
                {renderClarification(streamClarification)}
                {renderQuizPreview(streamQuiz)}
                {renderProcessPanel(buildProcessSnapshot(streamStages), "streaming-process")}
              </View>
            </View>
          ) : null}
          <View id="chat-bottom" />
        </View>
      </ScrollView>

      <View className="composer card">
        <Button
          className={`button-secondary web-search-toggle ${webSearchEnabled ? "active" : ""}`}
          disabled={isStreaming}
          onClick={toggleWebSearch}
        >
          <Text className="web-search-toggle-icon">网</Text>
          <Text className="web-search-toggle-label">{webSearchEnabled ? "联网开" : "联网"}</Text>
        </Button>
        <Textarea
          className="composer-input"
          value={inputValue}
          autoHeight
          maxlength={2000}
          placeholder="输入你的问题..."
          disabled={isStreaming}
          onInput={(event: any) => setInputValue(event.detail.value)}
        />
        <Button className="button-primary composer-button" disabled={!inputValue.trim() || isStreaming} onClick={handleSend}>
          {isStreaming ? "生成中" : "发送"}
        </Button>
      </View>

      {/* History Drawer */}
      {showHistory ? (
        <View className="history-overlay" onClick={() => setShowHistory(false)}>
          <View className="history-drawer" onClick={(e) => e.stopPropagation()}>
            <View className="drawer-header">
              <Text className="drawer-title">最近记录</Text>
              <Button className="button-secondary drawer-close" onClick={() => setShowHistory(false)}>关闭</Button>
            </View>
            <Button className="button-primary drawer-new" onClick={() => { setShowHistory(false); handleNewChat(); }}>开启新对话</Button>
            <ScrollView className="drawer-list" scrollY>
              <View className="drawer-list-inner">
                {sessionsLoading ? <Text className="drawer-empty">加载中...</Text> : null}
                {!sessionsLoading && sessions.length === 0 ? <Text className="drawer-empty">暂无聊天记录</Text> : null}
                {sessions.map((session) => {
                  const nb = notebooks.find((n) => n.id === session.notebookId);
                  return (
                    <View key={session.id} className={`session-card ${session.id === sessionId ? "active" : ""}`}>
                      <View className="session-main" onClick={() => handleSelectSession(session)}>
                        <Text className="session-icon">{nb?.icon || "📚"}</Text>
                        <View className="session-info">
                          <Text className="session-title">{session.title}</Text>
                          <Text className="session-meta">{nb?.name || "未知"} · {formatDate(session.updatedAt)} · {session.messageCount}条</Text>
                        </View>
                      </View>
                      <View className="session-delete" onClick={() => void handleDeleteSession(session.id)}>
                        <Text className="delete-text">删除</Text>
                      </View>
                    </View>
                  );
                })}
              </View>
            </ScrollView>
          </View>
        </View>
      ) : null}
    </View>
  );
}
