"""HTTP-framework regressions; synthetic content, no database or model calls."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__")

import app.interfaces.api.chat as chat_module
import app.interfaces.api.upload as upload_module
from app.interfaces.auth.dependencies import require_current_user
from app.interfaces.middleware.request_logging import RequestLoggingMiddleware
from app.shared.schemas.contracts import AuthUserView, IngestResult


def _application() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(upload_module.router, prefix="/api")
    app.include_router(chat_module.router, prefix="/api")
    app.dependency_overrides[require_current_user] = lambda: AuthUserView(
        id="transport-user", email="transport@example.invalid", display_name="Transport", status="active"
    )
    return app


class UploadFormLimitsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_application())
        self.addCleanup(self.client.close)

    def test_urlencoded_excess_fields_rejected_before_ingestion(self) -> None:
        with patch.object(upload_module, "ingest_pdf_bytes") as ingest:
            # A small form reaches ordinary missing-file validation.
            response = self.client.post("/api/upload", data={"subject_id": "computer-network"})
            self.assertEqual(response.status_code, 422)
            # Starlette < 1.3.1 ignored max_fields for this content type.
            response = self.client.post("/api/upload", data={f"field{i}": "x" for i in range(1001)})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Too many fields", response.json()["detail"])
            ingest.assert_not_called()

    def test_urlencoded_oversized_field_rejected_before_ingestion(self) -> None:
        with patch.object(upload_module, "ingest_pdf_bytes") as ingest:
            response = self.client.post("/api/upload", data={"subject_id": "x" * (1024 * 1024 + 1)})
            self.assertEqual(response.status_code, 400)
            ingest.assert_not_called()

    def test_multipart_oversized_text_field_rejected_before_ingestion(self) -> None:
        with patch.object(upload_module, "ingest_pdf_bytes") as ingest:
            response = self.client.post(
                "/api/upload",
                data={"subject_id": "x" * (1024 * 1024 + 1)},
                files={"file": ("synthetic.pdf", b"synthetic transport bytes", "application/pdf")},
            )
            self.assertEqual(response.status_code, 400)
            ingest.assert_not_called()

    def test_file_larger_than_spool_threshold_preserves_bytes_and_owner(self) -> None:
        # This checks multipart transport/spooling, not PDF parsing or embeddings.
        content = b"synthetic-file-content\n" * 60000
        result = IngestResult(
            filename="synthetic.pdf", total_pages=1, total_chunks=1,
            mapped_chunks=1, unmapped_chunks=0, subject_id="computer-network", message="synthetic",
        )
        with patch.object(upload_module, "ingest_pdf_bytes", return_value=result) as ingest:
            response = self.client.post(
                "/api/upload", data={"subject_id": "computer-network"},
                files={"file": ("synthetic.pdf", content, "application/pdf")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total_chunks"], 1)
            ingest.assert_called_once_with(
                filename="synthetic.pdf", content=content,
                subject_id="computer-network", user_id="transport-user",
            )


class ChatLoopbackHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.addCleanup(self.socket.close)
        self.base_url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(
            _application(), lifespan="off", log_level="warning", ws="none",
            timeout_graceful_shutdown=2,
        ))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.addCleanup(self._stop_server)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.started, "temporary HTTP server failed to start")

    def _stop_server(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "temporary HTTP server did not stop")
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None

    @staticmethod
    def _chunk() -> dict:
        return {"node": "meta_node", "state_update": {"final_answer": "synthetic-transport-answer"}, "elapsed": 0.01}

    @staticmethod
    def _request() -> dict:
        return {"user_id": "transport-user", "question": "synthetic transport question", "allow_web": False}

    def test_sse_completion_and_request_id_over_real_http(self) -> None:
        async def stream(**_kwargs):
            yield self._chunk()

        with patch.object(chat_module, "stream_chat", stream), httpx.Client(trust_env=False, timeout=5) as client:
            response = client.post(
                self.base_url + "/api/chat", json=self._request(), headers={"X-Request-ID": "transport-complete"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["x-request-id"], "transport-complete")
        self.assertIn("synthetic-transport-answer", response.text)
        self.assertIn("event: done", response.text)
        self.assertNotIn("event: error", response.text)

    def test_sse_disconnect_closes_pending_generator_over_real_http(self) -> None:
        closed = threading.Event()

        async def stream(**_kwargs):
            try:
                yield self._chunk()
                await asyncio.Event().wait()
            finally:
                closed.set()

        with patch.object(chat_module, "stream_chat", stream), httpx.Client(trust_env=False, timeout=5) as client:
            with client.stream("POST", self.base_url + "/api/chat", json=self._request()) as response:
                self.assertEqual(response.status_code, 200)
                for line in response.iter_lines():
                    if "synthetic-transport-answer" in line:
                        break
                else:
                    self.fail("SSE answer was buffered or lost")
                self.assertFalse(closed.is_set(), "generator should still be awaiting its next chunk")
            self.assertTrue(closed.wait(timeout=5), "disconnect did not close the pending generator")


if __name__ == "__main__":
    unittest.main()
