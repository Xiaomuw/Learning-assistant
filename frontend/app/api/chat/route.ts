import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INTERNAL_API_BASE = (
  process.env.INTERNAL_API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://127.0.0.1:8000/api"
).replace(/\/$/, "");

function buildProxyError(message: string, status = 502) {
  return new Response(JSON.stringify({ detail: message }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
    },
  });
}

export async function POST(request: NextRequest) {
  const upstreamUrl = `${INTERNAL_API_BASE}/chat`;
  const rawBody = await request.text();

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
      return buildProxyError("聊天代理未收到上游流式响应");
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
    const message =
      error instanceof Error ? `聊天代理连接失败：${error.message}` : "聊天代理连接失败";
    return buildProxyError(message);
  }
}
