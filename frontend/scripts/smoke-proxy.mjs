/** Minimal HTTP regression smoke for the Next 16 upgrade. No real credentials or DB. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const nextPort = 3105;
const mockPort = 18080;
const base = `http://127.0.0.1:${nextPort}`;
const mockBackend = createServer((req, res) => {
  if (req.url === "/api/__oss_probe") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok", method: req.method }));
  } else if (req.url === "/api/__oss_sse") {
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.end("data: smoke-pass\n\n");
  } else {
    res.writeHead(404);
    res.end("not found");
  }
});
await new Promise((resolve, reject) => {
  mockBackend.once("error", reject);
  mockBackend.listen(mockPort, "127.0.0.1", resolve);
});

const child = spawn(
  process.execPath,
  [join(root, "node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", String(nextPort)],
  {
    cwd: root,
    env: {
      ...process.env,
      NODE_ENV: "production",
      INTERNAL_API_BASE: `http://127.0.0.1:${mockPort}/api`,
      NEXT_TELEMETRY_DISABLED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let lastOutput = "";
for (const stream of [child.stdout, child.stderr]) {
  stream.on("data", (chunk) => {
    lastOutput = (lastOutput + chunk.toString()).slice(-4000);
  });
}

try {
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    if (child.exitCode != null) break;
    try {
      const response = await fetch(`${base}/login`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {
      // Web server is still booting.
    }
    await sleep(500);
  }
  assert.ok(ready, `Next server did not become ready. Logs: ${lastOutput}`);

  const login = await fetch(`${base}/login`, { redirect: "manual" });
  assert.equal(login.status, 200, "public login route must load");

  const unauth = await fetch(`${base}/chat`, { redirect: "manual" });
  assert.ok(unauth.status >= 300 && unauth.status < 400, "unauthenticated /chat must redirect");
  const target = new URL(unauth.headers.get("location"), base);
  assert.equal(target.pathname, "/login");
  assert.equal(target.searchParams.get("next"), "/chat");

  const cookieRoute = await fetch(`${base}/chat`, {
    headers: { cookie: "la_access_token=mock-token" },
    redirect: "manual",
  });
  assert.ok(cookieRoute.status >= 200 && cookieRoute.status < 300, "auth cookie should pass routing proxy");

  const api = await fetch(`${base}/api/__oss_probe`);
  assert.equal(api.status, 200, "API rewrite should reach mock backend");
  assert.deepEqual(await api.json(), { status: "ok", method: "GET" });

  const sse = await fetch(`${base}/api/__oss_sse`);
  assert.equal(sse.status, 200);
  assert.match(sse.headers.get("content-type") || "", /text\/event-stream/);
  assert.ok((await sse.text()).includes("data: smoke-pass"), "SSE text should reach client");

  console.log("Next 16 HTTP smoke: public route, protected route, cookie bypass, API rewrite and SSE passed.");
} finally {
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    sleep(3000),
  ]);
  await new Promise((resolve) => mockBackend.close(resolve));
}
