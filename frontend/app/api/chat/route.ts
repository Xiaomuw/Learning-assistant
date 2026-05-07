import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INTERNAL_API_BASE = (
  process.env.INTERNAL_API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://127.0.0.1:8000/api"
).replace(/\/$/, "");

const RETRYABLE_UPSTREAM_STATUS = new Set([502, 503, 504]);
const MAX_UPSTREAM_CONNECT_RETRIES = 2;

function buildProxyError(
  message: string,
  status = 502,
  extra?: { attempts?: number; retryable?: boolean; reason?: string },
) {
  return new Response(JSON.stringify({ detail: message, ...extra }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
    },
  });
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeProxyError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "上游学习引擎连接失败";
}

export async function POST(request: NextRequest) {
  const upstreamUrl = `${INTERNAL_API_BASE}/chat`;
  const rawBody = await request.text();
  let lastError: unknown = null;

  for (let attempt = 0; attempt <= MAX_UPSTREAM_CONNECT_RETRIES; attempt += 1) {
    try {
      const upstream = await fetch(upstreamUrl, {
        method: "POST",
        headers: {
          accept: "text/event-stream",
          "content-type": request.headers.get("content-type") ?? "application/json",
          cookie: request.headers.get("cookie") ?? "",
        },
        body: rawBody,
        cache: "no-store",
        signal: request.signal,
      });

      if (
        RETRYABLE_UPSTREAM_STATUS.has(upstream.status) &&
        attempt < MAX_UPSTREAM_CONNECT_RETRIES
      ) {
        lastError = new Error(`上游返回 ${upstream.status}`);
        await wait(300 * (attempt + 1));
        continue;
      }

      if (!upstream.ok) {
        const errorBody = await upstream.text();
        return new Response(errorBody || JSON.stringify({ detail: "聊天代理请求失败" }), {
          status: upstream.status,
          headers: {
            "Content-Type": upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
          },
        });
      }

      if (!upstream.body) {
        return buildProxyError("聊天代理未收到上游流式响应", 502, {
          attempts: attempt + 1,
          retryable: true,
          reason: "empty_stream",
        });
      }

      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
        },
      });
    } catch (error) {
      lastError = error;
      if (attempt < MAX_UPSTREAM_CONNECT_RETRIES) {
        await wait(300 * (attempt + 1));
        continue;
      }
    }
  }

  const reason = normalizeProxyError(lastError);
  return buildProxyError(
    `聊天代理连接失败：已自动重试 ${MAX_UPSTREAM_CONNECT_RETRIES} 次，仍无法连接后端学习引擎。原因：${reason}`,
    502,
    {
      attempts: MAX_UPSTREAM_CONNECT_RETRIES + 1,
      retryable: true,
      reason,
    },
  );
}
