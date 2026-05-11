import Taro from "@tarojs/taro";
import { clearAuthSession, getAccessToken } from "@/store/auth";
import { API_BASE, refreshAuthSession } from "@/services/api";
import type { ChatStreamDiagnostics, Explanation, SSEEvent } from "@/types/api";

export interface ChatStreamPayload {
  user_id: string;
  session_id: string;
  question: string;
  subject_id: string;
  thinking_mode?: boolean;
}

export interface ChatStreamHandlers {
  onEvent: (event: SSEEvent) => void;
  onDone?: () => void;
  onError?: (error: Error) => void;
  idleTimeoutMs?: number;
}

interface ParsedSSEMessage {
  event: string;
  data: string;
}

const MIN_CHAT_REQUEST_TIMEOUT_MS = 120000;
const CHAT_REQUEST_TIMEOUT_BUFFER_MS = 15000;
const STREAM_DIAGNOSTICS_THROTTLE_MS = 750;

function chatRequestTimeoutMs(idleTimeoutMs: number) {
  return Math.max(idleTimeoutMs + CHAT_REQUEST_TIMEOUT_BUFFER_MS, MIN_CHAT_REQUEST_TIMEOUT_MS);
}

function normalizeRequestError(error: any) {
  const message = String(error?.errMsg || error?.message || "").trim();
  if (/timeout/i.test(message)) return "聊天响应超时，请稍后重试。";
  if (/abort|aborted|cancel/i.test(message)) return "聊天连接已中断";
  return message || "聊天连接中断";
}

function decodeUtf8(buffer: ArrayBuffer, decoder: TextDecoder | null): string {
  const bytes = new Uint8Array(buffer);
  if (decoder) {
    return decoder.decode(bytes, { stream: true });
  }

  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  try {
    return decodeURIComponent(escape(binary));
  } catch {
    return binary;
  }
}

function parseData(raw: string) {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function errorTextFromData(data: any) {
  if (typeof data?.error === "string") return data.error;
  if (typeof data?.reason === "string") return data.reason;
  if (typeof data?.detail === "string") return data.detail;
  if (data?.detail && typeof data.detail === "object" && typeof data.detail.message === "string") {
    return data.detail.message;
  }
  if (data?.detail && typeof data.detail === "object" && typeof data.detail.reason === "string") {
    return data.detail.reason;
  }
  return "模型处理失败";
}

function stripMarkdownArtifacts(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[a-zA-Z]*\n?/g, "").replace(/```/g, ""))
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function buildAnswerContent(finalAnswer: string, explanation?: Explanation) {
  if (finalAnswer.trim()) {
    return stripMarkdownArtifacts(finalAnswer);
  }
  const stepContent = (explanation?.steps || [])
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
  if (stepContent) {
    return stripMarkdownArtifacts(stepContent);
  }
  if (explanation?.topic?.trim()) {
    return `我已经围绕「${stripMarkdownArtifacts(explanation.topic)}」整理好讲解了。`;
  }
  return "讲解已经准备好了。";
}

export function createSSEParser(onMessage: (message: ParsedSSEMessage) => void) {
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];

  function dispatch() {
    if (dataLines.length === 0) {
      eventName = "";
      return;
    }
    onMessage({
      event: eventName || "message",
      data: dataLines.join("\n")
    });
    eventName = "";
    dataLines = [];
  }

  function consumeLine(rawLine: string) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line) {
      dispatch();
      return;
    }
    if (line.startsWith(":")) {
      return;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  return {
    push(chunk: string) {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(consumeLine);
    },
    flush() {
      if (buffer) {
        consumeLine(buffer);
        buffer = "";
      }
      dispatch();
    }
  };
}

export function sendChatStream(payload: ChatStreamPayload, handlers: ChatStreamHandlers) {
  let completed = false;
  let activeTask: Taro.RequestTask<any> | null = null;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let lastDiagnosticsEmitAt = 0;
  const idleTimeoutMs = handlers.idleTimeoutMs ?? 90000;
  const requestTimeoutMs = chatRequestTimeoutMs(idleTimeoutMs);
  const startedAt = Date.now();
  const diagnostics: ChatStreamDiagnostics = {
    transport: "chunked",
    chunkSupported: false,
    chunkCount: 0,
    parsedEventCount: 0,
    realTokenDeltaCount: 0,
    syntheticDeltaCount: 0
  };

  const emitDiagnostics = (detail?: string, options: { force?: boolean } = {}) => {
    const now = Date.now();
    if (detail) diagnostics.detail = detail;
    if (
      !options.force &&
      lastDiagnosticsEmitAt > 0 &&
      now - lastDiagnosticsEmitAt < STREAM_DIAGNOSTICS_THROTTLE_MS
    ) {
      return;
    }
    lastDiagnosticsEmitAt = now;
    const diagnosticsPayload: ChatStreamDiagnostics = {
      ...diagnostics,
      detail: diagnostics.detail,
      elapsedMs: now - startedAt
    };
    handlers.onEvent({ event: "stream_diagnostics", data: diagnosticsPayload });
    const apiBase = process.env.TARO_APP_API_BASE || "";
    if (apiBase.includes("127.0.0.1") || apiBase.includes("localhost")) {
      console.info("[chat-stream]", diagnosticsPayload);
    }
  };

  const clearIdleTimer = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  const fail = (message: string) => {
    if (completed) return;
    completed = true;
    clearIdleTimer();
    handlers.onError?.(new Error(message));
  };

  const finish = () => {
    if (completed) return;
    completed = true;
    clearIdleTimer();
    handlers.onDone?.();
  };

  const scheduleIdleTimer = () => {
    clearIdleTimer();
    if (idleTimeoutMs <= 0 || completed) return;
    timeoutId = setTimeout(() => {
      fail("聊天响应超时，请稍后重试。");
      activeTask?.abort();
    }, idleTimeoutMs);
  };

  const dispatchEvent = (eventName: string, rawData: string) => {
    const data = parseData(rawData);
    diagnostics.parsedEventCount = (diagnostics.parsedEventCount || 0) + 1;
    let forceDiagnostics = false;
    if (eventName === "answer_delta") {
      const mode = typeof data?.streaming_mode === "string" ? data.streaming_mode : "token";
      const synthetic = Boolean(data?.is_synthetic_delta);
      if (mode === "token" && !synthetic) {
        diagnostics.realTokenDeltaCount = (diagnostics.realTokenDeltaCount || 0) + 1;
        if (diagnostics.firstRealTokenDeltaMs === undefined) {
          diagnostics.firstRealTokenDeltaMs = Date.now() - startedAt;
          forceDiagnostics = true;
        }
      } else {
        diagnostics.syntheticDeltaCount = (diagnostics.syntheticDeltaCount || 0) + 1;
        diagnostics.degradedReason = diagnostics.degradedReason || "node_synthetic_delta";
        forceDiagnostics = diagnostics.syntheticDeltaCount === 1;
      }
    }
    handlers.onEvent({ event: eventName, data });
    if (eventName === "answer_delta" || eventName === "done" || eventName === "error") {
      emitDiagnostics(eventName === "answer_delta" ? "收到回答片段" : "流式请求结束", {
        force: forceDiagnostics || eventName === "done" || eventName === "error"
      });
    }
    if (eventName === "done") {
      finish();
    } else if (eventName === "error") {
      fail(errorTextFromData(data));
    }
  };

  const expireAuthSession = () => {
    clearAuthSession();
    Taro.reLaunch({ url: "/pages/login/index" });
    fail("登录已过期，请重新登录");
  };

  const sendSyncFallback = async (hasRetried = false) => {
    diagnostics.transport = "sync_fallback";
    diagnostics.chunkSupported = false;
    diagnostics.degradedReason = "chunk_receiver_unavailable";
    emitDiagnostics("当前环境未提供 chunk 接收能力，已切换同步请求。", { force: true });
    try {
      const response = await Taro.request<any>({
        url: `${API_BASE}/chat/sync`,
        method: "POST",
        data: payload,
        header: {
          "Content-Type": "application/json",
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {})
        },
        timeout: requestTimeoutMs
      });
      if (response.statusCode === 401 && !hasRetried && (await refreshAuthSession())) {
        return sendSyncFallback(true);
      }
      if (response.statusCode === 401) {
        expireAuthSession();
        return;
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        fail(`聊天请求失败（${response.statusCode}）`);
        return;
      }
      const result = response.data || {};
      const explanation = result.explanation as Explanation | undefined;
      diagnostics.parsedEventCount = (diagnostics.parsedEventCount || 0) + 1;
      emitDiagnostics("同步请求已返回完整回答。", { force: true });
      handlers.onEvent({
        event: "explanation",
        data: {
          final_answer: buildAnswerContent(result.final_answer || "", explanation),
          explanation,
          question_type: result.question_type,
          route: result.route,
          session_id: result.session_id
        }
      });
      if (
        (Array.isArray(result.quiz_items) && result.quiz_items.length > 0) ||
        result.quiz_clarification ||
        result.quiz_generation_status
      ) {
        handlers.onEvent({
          event: "quiz",
          data: {
            quiz_items: Array.isArray(result.quiz_items) ? result.quiz_items : [],
            quiz_request: result.quiz_request,
            quiz_clarification: result.quiz_clarification,
            quiz_generation_status: result.quiz_generation_status,
            final_answer: result.final_answer,
            session_id: result.session_id,
            subject_id: payload.subject_id
          }
        });
      }
      if (result.memory) {
        handlers.onEvent({
          event: "memory",
          data: {
            memory: result.memory,
            session_id: result.session_id
          }
        });
      }
      handlers.onEvent({ event: "done", data: { message: "处理完成" } });
      finish();
    } catch (error: any) {
      fail(normalizeRequestError(error));
    }
  };

  const openStream = async (hasRetried = false) => {
    if (completed) return;
    const decoder = typeof TextDecoder !== "undefined" ? new TextDecoder("utf-8") : null;
    const parser = createSSEParser((message) => dispatchEvent(message.event, message.data));
    scheduleIdleTimer();

    activeTask = Taro.request({
      url: `${API_BASE}/chat`,
      method: "POST",
      data: payload,
      header: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {})
      },
      enableChunked: true,
      responseType: "arraybuffer",
      timeout: requestTimeoutMs
    });

    if (typeof activeTask.onChunkReceived !== "function") {
      activeTask.abort();
      await sendSyncFallback(hasRetried);
      return;
    }

    diagnostics.transport = "chunked";
    diagnostics.chunkSupported = true;
    emitDiagnostics("已建立 chunked 流式请求。", { force: true });

    activeTask.onChunkReceived((response) => {
      if (completed) return;
      scheduleIdleTimer();
      diagnostics.chunkCount = (diagnostics.chunkCount || 0) + 1;
      const isFirstChunk = diagnostics.firstChunkMs === undefined;
      if (diagnostics.firstChunkMs === undefined) {
        diagnostics.firstChunkMs = Date.now() - startedAt;
      }
      emitDiagnostics("收到网络 chunk。", { force: isFirstChunk });
      parser.push(decodeUtf8(response.data, decoder));
    });

    activeTask
      .then(async (response) => {
        if (completed) return;
        clearIdleTimer();
        if (response.statusCode === 401 && !hasRetried && (await refreshAuthSession())) {
          await openStream(true);
          return;
        }
        if (response.statusCode === 401) {
          expireAuthSession();
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          fail(`聊天请求失败（${response.statusCode}）`);
          return;
        }
        const remaining = decoder ? decoder.decode() : "";
        if (remaining) parser.push(remaining);
        parser.flush();
        emitDiagnostics("chunked 流式请求完成。", { force: true });
        finish();
      })
      .catch((error) => {
        if (!completed) {
          fail(normalizeRequestError(error));
        }
      });
  };

  openStream();

  return {
    abort() {
      completed = true;
      clearIdleTimer();
      activeTask?.abort();
    }
  };
}
