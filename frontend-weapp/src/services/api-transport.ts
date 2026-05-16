import Taro from "@tarojs/taro";

export const API_TRANSPORT = process.env.TARO_APP_API_TRANSPORT || "request";
export const API_BASE = process.env.TARO_APP_API_BASE || "";
export const CHAT_STREAM_API_BASE = process.env.TARO_APP_CHAT_STREAM_API_BASE || API_BASE;
export const CLOUD_ENV = process.env.TARO_APP_CLOUD_ENV || "";
export const CONTAINER_SERVICE = process.env.TARO_APP_CONTAINER_SERVICE || "";

type ApiMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface ApiTransportOptions {
  method?: ApiMethod;
  data?: any;
  header?: Record<string, string>;
  timeout?: number;
}

export interface ApiTransportResponse<T> {
  statusCode: number;
  data: T;
  header?: Record<string, any>;
  errMsg?: string;
  requestId?: string;
  clientRequestId?: string;
  callId?: string;
}

export interface ApiTransportFailureDiagnostics {
  code?: string | number;
  message: string;
  path: string;
  service: string;
  env: string;
  requestId?: string;
  clientRequestId?: string;
  callId?: string;
  retryable: boolean;
}

export class ApiTransportError extends Error {
  diagnostics: ApiTransportFailureDiagnostics;

  constructor(message: string, diagnostics: ApiTransportFailureDiagnostics) {
    super(message);
    this.name = "ApiTransportError";
    this.diagnostics = diagnostics;
  }
}

type WxCloudRuntime = {
  init?: (options?: { env?: string; traceUser?: boolean }) => void;
  callContainer?: <T = any>(options: {
    config?: { env?: string };
    path: string;
    method?: ApiMethod;
    data?: any;
    header?: Record<string, string>;
    timeout?: number;
    dataType?: "json" | "text";
  }) => Promise<ApiTransportResponse<T> & { callID?: string; requestID?: string }>;
};

let cloudInitialized = false;

function getWxCloud(): WxCloudRuntime | undefined {
  return (globalThis as any)?.wx?.cloud;
}

function normalizePath(path: string) {
  return path.startsWith("/") ? path : `/${path}`;
}

function buildContainerPath(path: string) {
  const normalized = normalizePath(path);
  return normalized === "/api" || normalized.startsWith("/api/")
    ? normalized
    : `/api${normalized}`;
}

function parseContainerText<T>(data: unknown): T {
  if (typeof data !== "string") return data as T;
  if (!data.trim()) return {} as T;
  try {
    return JSON.parse(data) as T;
  } catch {
    return data as T;
  }
}

function createClientRequestId() {
  return `weapp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function readHeader(headers: Record<string, any> | undefined, name: string) {
  if (!headers) return undefined;
  const normalized = name.toLowerCase();
  const key = Object.keys(headers).find((item) => item.toLowerCase() === normalized);
  const value = key ? headers[key] : undefined;
  return Array.isArray(value) ? value[0] : value;
}

function buildTraceHeaders(header: Record<string, string> | undefined) {
  const nextHeader = { ...(header || {}) };
  const existingRequestId =
    nextHeader["X-Request-ID"] ||
    nextHeader["x-request-id"] ||
    nextHeader["X-Client-Request-ID"] ||
    nextHeader["x-client-request-id"];
  const clientRequestId = existingRequestId || createClientRequestId();
  nextHeader["X-Client-Request-ID"] = clientRequestId;
  nextHeader["X-Request-ID"] = existingRequestId || clientRequestId;
  return { header: nextHeader, clientRequestId };
}

function extractCloudErrorCode(error: any): string | number | undefined {
  if (error?.errCode !== undefined) return error.errCode;
  if (error?.errcode !== undefined) return error.errcode;
  if (error?.code !== undefined) return error.code;
  const message = String(error?.errMsg || error?.message || "");
  const matched = message.match(/\bcode:\s*([\w-]+)|\bfail\s+([\w-]+)/i);
  return matched?.[1] || matched?.[2];
}

function isRetryableCloudError(message: string, code?: string | number) {
  const normalized = `${code || ""} ${message}`.toLowerCase();
  return (
    normalized.includes("102002") ||
    normalized.includes("system error") ||
    normalized.includes("timeout") ||
    normalized.includes("timed out") ||
    normalized.includes("connection") ||
    normalized.includes("network")
  );
}

function toCloudTransportError(error: any, path: string, clientRequestId: string) {
  const message = String(error?.errMsg || error?.message || "cloud.callContainer failed");
  const code = extractCloudErrorCode(error);
  const diagnostics: ApiTransportFailureDiagnostics = {
    code,
    message,
    path: buildContainerPath(path),
    service: CONTAINER_SERVICE,
    env: CLOUD_ENV,
    requestId: error?.requestID || error?.requestId,
    clientRequestId,
    callId: error?.callID || error?.callId,
    retryable: isRetryableCloudError(message, code)
  };
  console.warn("[api-transport] wx.cloud.callContainer 调用失败", diagnostics);
  return new ApiTransportError("云端服务暂时繁忙，请稍后重试。", diagnostics);
}

function isCloudRuntimeAvailable() {
  const cloud = getWxCloud();
  return Boolean(cloud?.init && cloud?.callContainer);
}

export function isContainerTransportEnabled() {
  return API_TRANSPORT === "container" && Boolean(CLOUD_ENV && CONTAINER_SERVICE);
}

export function initializeCloudContainer() {
  if (!isContainerTransportEnabled() || cloudInitialized) return;
  const cloud = getWxCloud();
  if (!cloud?.init) {
    console.warn("[api-transport] wx.cloud 不可用，无法初始化云托管调用。");
    return;
  }
  cloud.init({ env: CLOUD_ENV, traceUser: true });
  cloudInitialized = true;
}

async function callContainer<T>(
  path: string,
  options: ApiTransportOptions
): Promise<ApiTransportResponse<T>> {
  initializeCloudContainer();
  const cloud = getWxCloud();
  if (!cloud?.callContainer) {
    throw new Error("当前微信环境不支持云托管调用，请升级微信或基础库版本。");
  }

  const trace = buildTraceHeaders(options.header);
  let response: ApiTransportResponse<unknown> & { callID?: string; requestID?: string };
  try {
    response = await cloud.callContainer<unknown>({
      config: { env: CLOUD_ENV },
      path: buildContainerPath(path),
      method: options.method || "GET",
      data: options.data,
      header: {
        ...trace.header,
        "X-WX-SERVICE": CONTAINER_SERVICE
      },
      timeout: options.timeout,
      dataType: "text"
    });
  } catch (error) {
    throw toCloudTransportError(error, path, trace.clientRequestId);
  }

  return {
    statusCode: typeof response.statusCode === "number" ? response.statusCode : 200,
    data: parseContainerText<T>(response.data),
    header: response.header,
    errMsg: response.errMsg,
    requestId: response.requestID || readHeader(response.header, "X-Request-ID"),
    clientRequestId: trace.clientRequestId,
    callId: response.callID
  };
}

async function requestViaApiBase<T>(
  path: string,
  options: ApiTransportOptions
): Promise<ApiTransportResponse<T>> {
  const trace = buildTraceHeaders(options.header);
  const response = await Taro.request<T>({
    url: `${API_BASE}${normalizePath(path)}`,
    method: options.method || "GET",
    data: options.data,
    header: trace.header,
    timeout: options.timeout
  });
  return {
    statusCode: response.statusCode,
    data: response.data,
    header: response.header,
    errMsg: response.errMsg,
    requestId: readHeader(response.header, "X-Request-ID"),
    clientRequestId: trace.clientRequestId
  };
}

export function callApiTransport<T>(
  path: string,
  options: ApiTransportOptions = {}
): Promise<ApiTransportResponse<T>> {
  if (isContainerTransportEnabled()) {
    if (!isCloudRuntimeAvailable()) {
      throw new Error("当前微信环境不支持云托管调用，请升级微信或基础库版本。");
    }
    return callContainer<T>(path, options);
  }
  return requestViaApiBase<T>(path, options);
}
