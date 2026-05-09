from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.auth import service as auth_service  # noqa: E402
from app.application.errors import UnauthorizedError  # noqa: E402
from app.shared.schemas.contracts import AuthSessionResult, AuthUserView  # noqa: E402


class AuthRefreshReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        auth_service._refresh_replay_cache.clear()

    def tearDown(self) -> None:
        auth_service._refresh_replay_cache.clear()

    def test_refresh_token_short_replay_returns_same_session_once(self) -> None:
        user = AuthUserView(
            id="user-1",
            email="learner@example.com",
            display_name="Learner",
            status="active",
        )
        issued_session = AuthSessionResult(
            user=user,
            access_token="access-new",
            refresh_token="refresh-new",
        )

        with (
            patch(
                "app.application.auth.service.decode_token",
                return_value={"sub": "user-1", "jti": "jti-1"},
            ),
            patch(
                "app.application.auth.service.consume_refresh_token_record",
                side_effect=[object(), None, None],
            ),
            patch(
                "app.application.auth.service.get_user_auth_view_record",
                return_value=user,
            ),
            patch(
                "app.application.auth.service._issue_auth_session",
                return_value=issued_session,
            ) as issue_session,
        ):
            first = auth_service.refresh_user_session("old-refresh-token")
            replay = auth_service.refresh_user_session("old-refresh-token")

            with self.assertRaises(UnauthorizedError):
                auth_service.refresh_user_session("old-refresh-token")

        self.assertEqual(first, issued_session)
        self.assertEqual(replay, issued_session)
        issue_session.assert_called_once_with(user)


if __name__ == "__main__":
    unittest.main()
