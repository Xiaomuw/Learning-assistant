from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.observability.request_context import get_request_id
from app.interfaces.middleware.request_logging import RequestLoggingMiddleware


class RequestLoggingMiddlewareTest(unittest.TestCase):
    def _client(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/echo")
        def echo(request: Request):
            return {
                "state_request_id": request.state.request_id,
                "context_request_id": get_request_id(),
            }

        @app.get("/health")
        def health():
            return {"status": "ok"}

        return TestClient(app)

    def test_generates_request_id_and_returns_header(self) -> None:
        response = self._client().get("/echo")

        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("x-request-id")
        self.assertTrue(request_id)
        self.assertEqual(response.json()["state_request_id"], request_id)
        self.assertEqual(response.json()["context_request_id"], request_id)

    def test_reuses_valid_request_id_header(self) -> None:
        response = self._client().get("/echo", headers={"X-Request-ID": "weapp-test-123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-request-id"), "weapp-test-123")
        self.assertEqual(response.json()["state_request_id"], "weapp-test-123")

    def test_health_success_is_not_logged_as_regular_request(self) -> None:
        client = self._client()
        with (
            patch("app.interfaces.middleware.request_logging.logger.info") as info,
            patch("app.interfaces.middleware.request_logging.logger.warning") as warning,
            patch("app.interfaces.middleware.request_logging.logger.error") as error,
        ):
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("x-request-id"))
        info.assert_not_called()
        warning.assert_not_called()
        error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
