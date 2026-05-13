import Taro from "@tarojs/taro";
import { clearAuthSession, getAccessToken } from "@/store/auth";
import { API_BASE, refreshAuthSession } from "@/services/api";
import { ApiTransportError, callApiTransport, isContainerTransportEnabled } from "@/services/api-transport";
import {
  createSSEParser,
  decodeUtf8,
  recordStreamChunkDiagnostics,
  recordStreamEventDiagnostics
} from "@/services/chat-stream-core";
import type { ChatStreamDiagnostics, Explanation, SSEEvent } from "@/types/api";

export { createSSEParser } from "@/services/chat-stream-core";

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

const MIN_CHAT_REQUEST_TIMEOUT_MS = 120000;
const CHAT_REQUEST_TIMEOUT_BUFFER_MS = 15000;
const STREAM_DIAGNOSTICS_THROTTLE_MS = 750;
const CHAT_JOB_DEFAULT_RETRY_AFTER_MS = 2000;
const CHAT_JOB_MAX_POLL_MS = 90000;

function chatRequestTimeoutMs(idleTimeoutMs: number) {
  return Math.max(idleTimeoutMs + CHAT_REQUEST_TIMEOUT_BUFFER_MS, MIN_CHAT_REQUEST_TIMEOUT_MS);
}

function normalizeRequestError(error: any) {
  if (error instanceof ApiTransportError) {
    return "云端服务暂时繁忙，请稍后重试。";
  }
  const message = String(error?.errMsg || error?.message || "").trim();
  if (/timeout/i.test(message)) return "聊天响应超时，请稍后重试。";
  if (/abort|aborted|cancel/i.test(message)) return "聊天连接已中断";
  if (/callcontainer|102002|system error/i.test(message)) return "云端服务暂时繁忙，请稍后重试。";
  return message || "聊天连接中断";
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

function friendlyChatErrorFromData(data: any, statusCode: number) {
  const reason = String(data?.reason || data?.error_type || "").toLowerCase();
  if (reason === "timeout") return "模型响应超时，请稍后重试，或把问题拆小后再问。";
  if (reason === "model_unavailable") return "当前模型服务暂时不可用，请稍后重试。";
  const text = errorTextFromData(data);
  if (/callcontainer|102002|system error/i.test(text)) return "云端服务暂时繁忙，请稍后重试。";
  return text || `聊天请求失败（${statusCode}）`;
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    const diagnosticUpdate = recordStreamEventDiagnostics(
      diagnostics,
      eventName,
      data,
      Date.now() - startedAt
    );
    handlers.onEvent({ event: eventName, data });
    if (eventName === "answer_delta" || eventName === "done" || eventName === "error") {
      emitDiagnostics(eventName === "answer_delta" ? "收到回答片段" : "流式请求结束", {
        force: diagnosticUpdate.force || eventName === "done" || eventName === "error"
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

  const emitAsyncJobStatus = (detail: string, extra: Record<string, any> = {}) => {
    handlers.onEvent({
      event: "status",
      data: {
        stream_stage: "chat_async_job",
        stage_label: "云托管后台处理",
        detail,
        status: "running",
        streaming_mode: "sync",
        session_id: payload.session_id,
        ...extra
      }
    });
    emitDiagnostics(detail, { force: true });
  };

  const dispatchCompletedSyncResponse = (result: any, detail = "同步请求已返回完整回答。") => {
    if (completed) return;
    const explanation = result.explanation as Explanation | undefined;
    diagnostics.parsedEventCount = (diagnostics.parsedEventCount || 0) + 1;
    emitDiagnostics(detail, { force: true });
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
  };

  const pollChatJob = async (jobId: string, retryAfterMs?: number, hasRetriedAuth = false) => {
    const deadlineAt = Date.now() + CHAT_JOB_MAX_POLL_MS;
    let nextDelayMs = Math.max(
      1000,
      Math.min(10000, retryAfterMs || CHAT_JOB_DEFAULT_RETRY_AFTER_MS)
    );
    let fallbackToGet = false;
    let shouldDelayBeforePoll = false;
    const shortId = (value?: string) => {
      const text = String(value || "").trim();
      return text ? text.slice(0, 12) : "";
    };
    const pollTraceExtra = () => ({
      job_id: jobId,
      request_id: diagnostics.requestId,
      client_request_id: diagnostics.clientRequestId,
      call_id: diagnostics.callId
    });
    const pollTraceSuffix = () => {
      const parts = [
        shortId(jobId) ? `job=${shortId(jobId)}` : "",
        shortId(diagnostics.requestId) ? `request=${shortId(diagnostics.requestId)}` : "",
        shortId(diagnostics.clientRequestId) ? `client=${shortId(diagnostics.clientRequestId)}` : "",
        shortId(diagnostics.callId) ? `call=${shortId(diagnostics.callId)}` : ""
      ].filter(Boolean);
      return parts.length ? ` 诊断：${parts.join(" · ")}` : "";
    };
    const emitPollStatus = (detail: string) => {
      emitAsyncJobStatus(`${detail}${pollTraceSuffix()}`, pollTraceExtra());
    };
    emitPollStatus("后台结果轮询中，正在联网搜索并整理答案。");
    while (!completed && Date.now() < deadlineAt) {
      if (shouldDelayBeforePoll) {
        await delay(nextDelayMs);
      }
      shouldDelayBeforePoll = true;
      if (completed) return;
      let response;
      try {
        const encodedJobId = encodeURIComponent(jobId);
        const pollPath = fallbackToGet
          ? `/chat/jobs/${encodedJobId}`
          : `/chat/jobs/${encodedJobId}/poll`;
        response = await callApiTransport<any>(pollPath, {
          method: fallbackToGet ? "GET" : "POST",
          data: fallbackToGet ? undefined : {},
          header: {
            ...(fallbackToGet ? {} : { "Content-Type": "application/json" }),
            ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {})
          },
          timeout: requestTimeoutMs
        });
      } catch (error: any) {
        if (error instanceof ApiTransportError) {
          diagnostics.requestId = error.diagnostics.requestId;
          diagnostics.clientRequestId = error.diagnostics.clientRequestId;
          diagnostics.callId = error.diagnostics.callId;
          diagnostics.degradedReason = "cloud_container_job_poll_error";
          emitPollStatus("后台结果轮询暂时未接入后端，继续等待。");
          continue;
        }
        fail(normalizeRequestError(error));
        return;
      }

      if (response.statusCode === 401 && !hasRetriedAuth && (await refreshAuthSession())) {
        await pollChatJob(jobId, nextDelayMs, true);
        return;
      }
      if (response.statusCode === 401) {
        expireAuthSession();
        return;
      }
      diagnostics.requestId = response.data?.request_id || response.requestId || diagnostics.requestId;
      diagnostics.clientRequestId = response.clientRequestId || diagnostics.clientRequestId;
      diagnostics.callId = response.callId || diagnostics.callId;
      if (!fallbackToGet && (response.statusCode === 404 || response.statusCode === 405)) {
        fallbackToGet = true;
        diagnostics.degradedReason = "chat_job_post_poll_fallback_to_get";
        shouldDelayBeforePoll = false;
        emitPollStatus("POST 轮询暂不可用，已切换 GET 轮询。");
        continue;
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        diagnostics.degradedReason = String(response.data?.reason || "chat_job_http_error");
        fail(friendlyChatErrorFromData(response.data, response.statusCode));
        return;
      }

      const job = response.data || {};
      nextDelayMs = Math.max(
        1000,
        Math.min(10000, Number(job.retry_after_ms || nextDelayMs || CHAT_JOB_DEFAULT_RETRY_AFTER_MS))
      );
      if (job.status === "completed" && job.response) {
        dispatchCompletedSyncResponse(job.response, "后台答案已完成。");
        return;
      }
      if (job.status === "failed") {
        diagnostics.degradedReason = String(job.error?.reason || "chat_job_failed");
        fail(friendlyChatErrorFromData(job.error || job, 500));
        return;
      }
      emitPollStatus("仍在联网搜索并整理答案。");
    }
    fail("答案仍在生成中，请稍后重试获取结果。");
  };

  const sendSyncFallback = async (
    hasRetried = false,
    degradedReason = "chunk_receiver_unavailable"
  ) => {
    diagnostics.transport =
      degradedReason.startsWith("cloud_container") ? "cloud_container_sync" : "sync_fallback";
    diagnostics.chunkSupported = false;
    diagnostics.degradedReason = degradedReason;
    emitDiagnostics(
      degradedReason.startsWith("cloud_container")
        ? "当前使用云托管容器调用，已切换同步请求。"
        : "当前环境未提供 chunk 接收能力，已切换同步请求。",
      { force: true }
    );
    try {
      const response = await callApiTransport<any>("/chat/sync", {
        method: "POST",
        data: payload,
        header: {
          "Content-Type": "application/json",
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {})
        },
        timeout: requestTimeoutMs
      });
      if (response.statusCode === 401 && !hasRetried && (await refreshAuthSession())) {
        return sendSyncFallback(true, degradedReason);
      }
      if (response.statusCode === 401) {
        expireAuthSession();
        return;
      }
      diagnostics.requestId = response.requestId;
      diagnostics.clientRequestId = response.clientRequestId;
      diagnostics.callId = response.callId;
      if (response.statusCode < 200 || response.statusCode >= 300) {
        diagnostics.degradedReason = String(response.data?.reason || "cloud_container_http_error");
        emitDiagnostics("云托管聊天接口返回异常。", { force: true });
        fail(friendlyChatErrorFromData(response.data, response.statusCode));
        return;
      }
      const result = response.data || {};
      if (result.status === "pending" && result.job_id) {
        diagnostics.degradedReason = "chat_async_job_pending";
        diagnostics.requestId = result.request_id || diagnostics.requestId;
        await pollChatJob(result.job_id, result.retry_after_ms);
        return;
      }
      dispatchCompletedSyncResponse(result);
    } catch (error: any) {
      if (error instanceof ApiTransportError) {
        diagnostics.requestId = error.diagnostics.requestId;
        diagnostics.clientRequestId = error.diagnostics.clientRequestId;
        diagnostics.callId = error.diagnostics.callId;
        diagnostics.degradedReason = "cloud_container_error";
        const isCloudContainerSync = diagnostics.transport === "cloud_container_sync";
        emitDiagnostics(
          isCloudContainerSync ? "云托管同步调用异常，已停止本轮处理。" : "云托管调用异常，准备进行一次重试。",
          { force: true }
        );
        if (!isCloudContainerSync && !hasRetried && error.diagnostics.retryable) {
          await delay(800);
          if (!completed) {
            return sendSyncFallback(true, "cloud_container_transport_retry");
          }
        }
        emitDiagnostics("云托管调用异常，已停止本轮处理。", { force: true });
      }
      fail(normalizeRequestError(error));
    }
  };

  const openStream = async (hasRetried = false) => {
    if (completed) return;
    if (isContainerTransportEnabled()) {
      await sendSyncFallback(hasRetried, "cloud_container_transport");
      return;
    }
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
      const diagnosticUpdate = recordStreamChunkDiagnostics(diagnostics, Date.now() - startedAt);
      emitDiagnostics("收到网络 chunk。", { force: diagnosticUpdate.force });
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
