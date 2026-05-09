import Taro from "@tarojs/taro";
import { getAccessToken } from "@/store/auth";
import { API_BASE, refreshAuthSession } from "@/services/api";
import type { SSEEvent } from "@/types/api";

export interface ChatStreamPayload {
  user_id: string;
  session_id: string;
  question: string;
  subject_id: string;
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
  return "学习引擎处理失败";
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
  const idleTimeoutMs = handlers.idleTimeoutMs ?? 90000;

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
      activeTask?.abort();
      fail("聊天响应超时，请稍后重试。");
    }, idleTimeoutMs);
  };

  const dispatchEvent = (eventName: string, rawData: string) => {
    const data = parseData(rawData);
    handlers.onEvent({ event: eventName, data });
    if (eventName === "done") {
      finish();
    } else if (eventName === "error") {
      fail(errorTextFromData(data));
    }
  };

  const sendSyncFallback = async (hasRetried = false) => {
    try {
      const response = await Taro.request<any>({
        url: `${API_BASE}/chat/sync`,
        method: "POST",
        data: payload,
        header: {
          "Content-Type": "application/json",
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {})
        }
      });
      if (response.statusCode === 401 && !hasRetried && (await refreshAuthSession())) {
        return sendSyncFallback(true);
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        fail(`聊天请求失败（${response.statusCode}）`);
        return;
      }
      const result = response.data || {};
      handlers.onEvent({
        event: "explanation",
        data: {
          final_answer: result.explanation?.thinking || "",
          explanation: result.explanation,
          question_type: result.question_type,
          route: result.route
        }
      });
      if (Array.isArray(result.quiz_items) && result.quiz_items.length > 0) {
        handlers.onEvent({
          event: "quiz",
          data: {
            quiz_items: result.quiz_items,
            quiz_request: result.quiz_request,
            quiz_clarification: result.quiz_clarification
          }
        });
      }
      handlers.onEvent({ event: "done", data: { message: "处理完成" } });
      finish();
    } catch (error: any) {
      fail(error?.message || "聊天连接中断");
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
      responseType: "arraybuffer"
    });

    if (typeof activeTask.onChunkReceived !== "function") {
      activeTask.abort();
      await sendSyncFallback(hasRetried);
      return;
    }

    activeTask.onChunkReceived((response) => {
      if (completed) return;
      scheduleIdleTimer();
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
        if (response.statusCode < 200 || response.statusCode >= 300) {
          fail(`聊天请求失败（${response.statusCode}）`);
          return;
        }
        const remaining = decoder ? decoder.decode() : "";
        if (remaining) parser.push(remaining);
        parser.flush();
        finish();
      })
      .catch((error) => {
        if (!completed) {
          fail(error?.errMsg || error?.message || "聊天连接中断");
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
