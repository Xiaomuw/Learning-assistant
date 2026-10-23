"""Exercise actual dependency boundaries with synthetic files and loopback HTTP."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure.ingest.web import extract_text_from_url


class SyntheticPage(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/note":
            self.send_error(404)
            return
        body = b"<html><nav>ignored navigation</nav><main>Synthetic HTTP lesson.</main><script>ignored script</script></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


class HttpEnvDependencyTest(unittest.TestCase):
    def test_real_url_parser_extracts_body_and_rejects_http_error(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticPage)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}):
                base = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(extract_text_from_url(base + "/note"), "Synthetic HTTP lesson.")
                self.assertIsNone(extract_text_from_url(base + "/missing"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dotenv_preserves_injected_config_and_expands_local_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('LA_TEST_BASE=file-value\nLA_TEST_URL=${LA_TEST_BASE}/api\nLA_TEST_TITLE="Synthetic Lesson"\n', encoding="utf-8")
            os.environ["LA_TEST_BASE"] = "injected-value"
            self.assertTrue(load_dotenv(path, override=False))
            self.assertEqual(os.environ["LA_TEST_BASE"], "injected-value")
            self.assertEqual(os.environ["LA_TEST_URL"], "injected-value/api")
            self.assertEqual(os.environ["LA_TEST_TITLE"], "Synthetic Lesson")


if __name__ == "__main__":
    unittest.main()
