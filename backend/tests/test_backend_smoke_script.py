from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import smoke_backend


class BackendSmokeScriptTest(unittest.TestCase):
    def test_join_url_handles_slashes(self) -> None:
        self.assertEqual(
            smoke_backend._join_url("http://127.0.0.1:8000/", "/api/auth/me"),
            "http://127.0.0.1:8000/api/auth/me",
        )

    def test_temporary_email_is_cleanup_safe(self) -> None:
        email = smoke_backend._temporary_email()

        self.assertTrue(email.startswith("codex+auth-auto-smoke-"))
        self.assertTrue(email.endswith("@gmail.com"))
        smoke_backend._validate_generated_email(email)

    def test_existing_account_requires_password(self) -> None:
        args = argparse.Namespace(email="smoke@example.com", password="")

        with self.assertRaises(smoke_backend.SmokeFailure):
            smoke_backend._build_account(args)


if __name__ == "__main__":
    unittest.main()
