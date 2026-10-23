#!/usr/bin/env python3
"""Check only the disposable la-ci stack started by the Compose CI workflow.

No models or external services are called. Liveness is not database readiness.
"""
import json
import subprocess
import time
import urllib.error
import urllib.request

command = ["docker", "compose", "-p", "la-ci", "--file", "docker-compose.yml"]
expected = {
    ("postgres", "5432"): "127.0.0.1:5434",
    ("backend", "8000"): "127.0.0.1:8003",
    ("frontend", "3000"): "127.0.0.1:3003",
}
for (service, internal), binding in expected.items():
    actual = subprocess.check_output(
        command + ["port", service, internal], text=True
    ).strip()
    assert actual == binding, f"Unexpected binding for {service}: {actual}"
    print(f"PASS: {service} host port remains loopback-only", flush=True)

def request(path):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{path[0]}{path[1]}", timeout=3
        ) as response:
            return response.status, response.read(2048)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2048)

deadline = time.monotonic() + 200
while time.monotonic() < deadline:
    try:
        b_status, b_body = request((8003, "/health"))
        f_status, _ = request((3003, "/login"))
        if b_status == 200 and f_status == 200:
            assert json.loads(b_body)["status"] == "ok"
            print("PASS: FastAPI liveness 200 (database readiness checked separately)", flush=True)
            print("PASS: clean Next.js frontend /login 200", flush=True)
            break
    except Exception:
        pass
    time.sleep(3)
else:
    raise SystemExit("Fresh Compose stack did not become ready")

anonymous_status, _ = request((3003, "/api/auth/me"))
assert anonymous_status == 401, f"Unauthorized API expected 401: got {anonymous_status}"
print("PASS: frontend API proxy routes to real backend and rejects anonymous access", flush=True)
