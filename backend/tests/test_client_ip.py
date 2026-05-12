from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.interfaces.client_ip import resolve_client_host


class ClientIpResolutionTest(unittest.TestCase):
    def test_uses_peer_host_without_proxy_headers(self) -> None:
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXY_IPS": ""}, clear=False):
            host = resolve_client_host(peer_host="10.0.0.5", headers={})

        self.assertEqual(host, "10.0.0.5")

    def test_ignores_forwarded_headers_when_peer_is_not_trusted(self) -> None:
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXY_IPS": ""}, clear=False):
            host = resolve_client_host(
                peer_host="10.0.0.5",
                headers={"X-Forwarded-For": "203.0.113.8", "X-Real-IP": "203.0.113.9"},
            )

        self.assertEqual(host, "10.0.0.5")

    def test_uses_first_valid_forwarded_for_from_trusted_proxy(self) -> None:
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXY_IPS": "127.0.0.1,10.0.0.0/8"}, clear=False):
            host = resolve_client_host(
                peer_host="10.1.2.3",
                headers={"X-Forwarded-For": "203.0.113.8, 10.1.2.3"},
            )

        self.assertEqual(host, "203.0.113.8")

    def test_falls_back_to_real_ip_then_peer_for_trusted_proxy(self) -> None:
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXY_IPS": "10.0.0.0/8"}, clear=False):
            real_ip = resolve_client_host(
                peer_host="10.1.2.3",
                headers={"X-Forwarded-For": "unknown, invalid", "X-Real-IP": "198.51.100.7"},
            )
            peer_ip = resolve_client_host(
                peer_host="10.1.2.3",
                headers={"X-Forwarded-For": "unknown", "X-Real-IP": "invalid"},
            )

        self.assertEqual(real_ip, "198.51.100.7")
        self.assertEqual(peer_ip, "10.1.2.3")


if __name__ == "__main__":
    unittest.main()
