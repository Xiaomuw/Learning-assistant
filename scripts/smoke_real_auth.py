#!/usr/bin/env python3
"""Exercise Next.js -> actual FastAPI -> disposable PostgreSQL authentication.

The only substitute is a loopback SMTP sink: it accepts real SMTP messages but
never delivers them externally. No auth/router/database implementation is mocked.
This is HTTP integration, not browser-click, external email, LLM, or TLS testing.
"""
from __future__ import annotations

import argparse
import contextlib
import email.policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
EXPECTED_DATABASE = "learning_assistant_web_e2e_test"
BACKEND_URL = "http://127.0.0.1:18080"
WEB_URL = "http://127.0.0.1:3107"


class LocalSMTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        self.messages: queue.Queue[bytes] = queue.Queue()
        super().__init__(("127.0.0.1", 0), SMTPHandler)


class SMTPHandler(socketserver.StreamRequestHandler):
    """Minimal loopback SMTP sink; no TLS, relay, or credential validation."""

    def reply(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        self.connection.settimeout(15)
        self.reply(b"220 localhost test SMTP sink")
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return
            command = line.split(b" ", 1)[0].strip().upper()
            if command in (b"EHLO", b"HELO"):
                self.reply(b"250-localhost")
                self.reply(b"250-AUTH PLAIN")
                self.reply(b"250 SIZE 1048576")
            elif command == b"AUTH":
                if len(line.strip().split()) < 3:
                    self.reply(b"334 ")
                    self.rfile.readline(65536)
                self.reply(b"235 Authentication successful")
            elif command in (b"MAIL", b"RCPT", b"RSET", b"NOOP"):
                self.reply(b"250 OK")
            elif command == b"DATA":
                self.reply(b"354 End with a single dot")
                chunks: list[bytes] = []
                size = 0
                while True:
                    data = self.rfile.readline(65536)
                    if not data:
                        return
                    if data in (b".\r\n", b".\n"):
                        break
                    size += len(data)
                    if size > 1048576:
                        self.reply(b"552 Test message too large")
                        return
                    chunks.append(data[1:] if data.startswith(b"..") else data)
                self.server.messages.put(b"".join(chunks))  # type: ignore[attr-defined]
                self.reply(b"250 Accepted by local test sink")
            elif command == b"QUIT":
                self.reply(b"221 Bye")
                return
            else:
                self.reply(b"502 Unsupported in test sink")


def demand(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_for_service(url: str, process: subprocess.Popen, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("A local test service exited before readiness")
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise TimeoutError("Local service readiness timed out")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def verification_code(sink: LocalSMTP, recipient: str) -> str:
    message = BytesParser(policy=email.policy.default).parsebytes(sink.messages.get(timeout=15))
    demand(recipient in str(message.get("To", "")), "SMTP recipient mismatch")
    text = "\n".join(
        part.get_content()
        for part in message.walk()
        if part.get_content_type() == "text/plain"
    )
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    demand(match is not None, "No six-digit verification code in local SMTP message")
    return match.group(1)  # type: ignore[union-attr]


def exercise_auth(sink: LocalSMTP) -> list[str]:
    passed: list[str] = []
    email_address = f"ci-{secrets.token_hex(8)}@example.com"
    password = "Ci!" + secrets.token_urlsafe(20)
    new_password = "CiChanged!" + secrets.token_urlsafe(20)

    def check(condition: bool, label: str) -> None:
        demand(condition, label)
        passed.append(label)
        print("PASS: " + label, flush=True)

    with httpx.Client(base_url=WEB_URL, timeout=20, trust_env=False, follow_redirects=False) as client:
        response = client.get("/practice?topic=ci")
        check(response.status_code in (302, 307, 308) and "/login" in response.headers.get("location", ""),
              "anonymous protected page redirects to login")
        check(client.get("/api/auth/me").status_code == 401, "anonymous API request rejected by real backend")
        response = client.post("/api/auth/register/send-code", json={"email": email_address})
        check(response.status_code == 200, "registration email sent through real SMTP client to local sink")
        code = verification_code(sink, email_address)
        response = client.post("/api/auth/register/complete", json={
            "email": email_address, "code": code, "password": password, "display_name": "Isolated CI User"
        })
        check(response.status_code == 201, "registration persisted in real PostgreSQL")
        cookies = response.headers.get_list("set-cookie")
        check(all(any(name + "=" in value and "httponly" in value.lower() for value in cookies)
                  for name in ("la_access_token", "la_refresh_token")),
              "Next.js forwards both HttpOnly authentication cookies")
        response = client.get("/api/auth/me")
        check(response.status_code == 200 and response.json()["user"]["email"] == email_address,
              "authenticated current-user request passes through Next.js to FastAPI")
        # Deterministic arithmetic exercises the actual graph and SSE endpoint,
        # without a provider key, fake backend, or mocked stream implementation.
        user_id = response.json()["user"]["id"]
        events: list[tuple[str, dict]] = []
        with client.stream("POST", "/api/chat", json={
            "user_id": user_id, "session_id": "ci-sse-" + secrets.token_hex(8),
            "question": "1+1等于几", "allow_web": False, "auto_web_fallback": False,
        }) as stream:
            check(stream.status_code == 200, "authenticated real chat stream opens through Next.js")
            check("text/event-stream" in stream.headers.get("content-type", ""),
                  "real backend SSE content type survives the proxy")
            event_name = "message"
            data: list[str] = []
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    events.append((event_name, json.loads("\n".join(data))))
                    event_name, data = "message", []
        check(bool(events) and events[-1][0] == "done", "actual SSE terminates with done")
        check(all(name != "error" for name, _ in events), "actual SSE contains no error event")
        check(any("2" in str(payload.get("final_answer", "")) for _, payload in events),
              "actual LangGraph arithmetic answer reaches the HTTP client")
        check(not any(payload.get("web_search_used") or payload.get("external_tool_calls")
                      for _, payload in events), "deterministic SSE does not use external tools")
        check(client.get("/practice").status_code == 200, "real authentication cookie opens protected page")
        old_refresh = client.cookies.get("la_refresh_token")
        response = client.post("/api/auth/refresh")
        check(response.status_code == 200 and bool(client.cookies.get("la_refresh_token"))
              and client.cookies.get("la_refresh_token") != old_refresh,
              "refresh rotates token through real proxy and database")
        check(client.post("/api/auth/logout").status_code == 200, "real logout endpoint succeeds")
        check(not client.cookies.get("la_access_token") and not client.cookies.get("la_refresh_token"),
              "logout removes both client cookies")
        check(client.get("/api/auth/me").status_code == 401, "logout revokes authenticated API session")
        check(client.get("/practice").status_code in (302, 307, 308), "logout restores protected-page redirect")
        response = client.post("/api/auth/login", json={"email": email_address, "password": password + "wrong"})
        check(response.status_code == 401, "incorrect password is rejected")
        response = client.post("/api/auth/login", json={"email": email_address, "password": password})
        check(response.status_code == 200, "stored password successfully logs in")
        response = client.post("/api/auth/change-password", json={
            "current_password": password, "new_password": new_password
        })
        check(response.status_code == 200, "password change persists via actual API")
        client.post("/api/auth/logout")
        response = client.post("/api/auth/login", json={"email": email_address, "password": password})
        check(response.status_code == 401, "previous password rejected after password change")
        response = client.post("/api/auth/login", json={"email": email_address, "password": new_password})
        check(response.status_code == 200, "changed password successfully logs in")
        client.post("/api/auth/logout")
    with httpx.Client(base_url=WEB_URL, timeout=10, trust_env=False) as forged:
        forged.cookies.set("la_access_token", "invalid-synthetic-token")
        check(forged.get("/api/auth/me").status_code == 401,
              "fake frontend cookie cannot authorize backend API access")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-disposable-db", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(database_url)
    demand(args.allow_disposable_db, "Explicit disposable-database approval is required")
    demand(parsed.hostname in ("127.0.0.1", "localhost"), "Only loopback database hosts allowed")
    demand(parsed.path.strip("/") == EXPECTED_DATABASE, "Refusing non-test database")
    demand(not (BACKEND / ".env").exists() and not (ROOT / ".env").exists(),
           "Refusing checkout containing actual .env files")
    demand((FRONTEND / ".next" / "BUILD_ID").is_file(), "Build the Next.js client before this test")
    with contextlib.ExitStack() as stack:
        sink = LocalSMTP()
        stack.callback(sink.server_close)
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        stack.callback(sink.shutdown)
        environment = dict(os.environ)
        environment.update({
            "APP_ENV": "development", "AUTH_COOKIE_SECURE": "false",
            "JWT_SECRET_KEY": secrets.token_hex(32), "ENABLE_GRAPH_FACTS": "false",
            "ENABLE_GRAPH_DUAL_WRITE": "false", "ENABLE_PRACTICE_FINALIZER_WORKER": "false",
            "MCP_ENABLED": "false", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
            "GRAPH_EVAL_LANGSMITH": "false", "MODEL_ACCESS_KEY": "", "OPENAI_API_KEY": "",
            "GOOGLE_API_KEYS": "", "TAVILY_API_KEY": "", "LANGSMITH_API_KEY": "",
            "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(sink.server_address[1]),
            "SMTP_USERNAME": "local-ci-sink", "SMTP_PASSWORD": secrets.token_hex(16),
            "SMTP_FROM_EMAIL": "ci@learning.invalid", "SMTP_USE_TLS": "false", "SMTP_USE_SSL": "false",
            "CORS_ALLOW_ORIGINS": WEB_URL, "LOG_LEVEL": "WARNING",
            "NEXT_TELEMETRY_DISABLED": "1", "INTERNAL_API_BASE": BACKEND_URL + "/api",
        })
        # These commands write ONLY to the explicitly guarded disposable DB.
        subprocess.run([sys.executable, "scripts/run_migrations_with_diagnostics.py"],
                       cwd=BACKEND, env=environment, check=True, timeout=120)
        subprocess.run([sys.executable, "scripts/bootstrap_app_data.py", "--confirm", "BOOTSTRAP_APP_DATA"],
                       cwd=BACKEND, env=environment, check=True, timeout=60)
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="la-auth-e2e-")))
        backend_log = stack.enter_context((temporary / "backend.log").open("w+"))
        web_log = stack.enter_context((temporary / "web.log").open("w+"))
        backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                    "--port", "18080", "--no-access-log"],
                                   cwd=BACKEND, env=environment, stdout=backend_log, stderr=subprocess.STDOUT)
        stack.callback(stop_process, backend)
        web = subprocess.Popen(["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "3107"],
                               cwd=FRONTEND, env=environment, stdout=web_log, stderr=subprocess.STDOUT)
        stack.callback(stop_process, web)
        try:
            wait_for_service(BACKEND_URL + "/health", backend)
            wait_for_service(WEB_URL + "/login", web)
            passed = exercise_auth(sink)
            print(json.dumps({"real_http_auth_checks_passed": len(passed),
                              "backend": "actual FastAPI app and PostgreSQL", "frontend": "production Next.js server",
                              "external_email_delivery": False, "llm_calls": False,
                              "production_deployment": False}, sort_keys=True))
        except Exception:
            for label, handle in (("backend", backend_log), ("frontend", web_log)):
                handle.flush()
                handle.seek(0)
                tail = "".join(handle.readlines()[-30:])
                for value in (environment["JWT_SECRET_KEY"], environment["SMTP_PASSWORD"], database_url):
                    tail = tail.replace(value, "[redacted]")
                tail = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted-token]", tail)
                print(f"{label} startup diagnostic:\n{tail}", file=sys.stderr)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
