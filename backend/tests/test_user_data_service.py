from __future__ import annotations

import unittest
import os
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.user_data.service import update_profile
from app.shared.schemas.contracts import UserProfileRecord


class UserDataServiceTest(unittest.TestCase):
    def test_update_profile_preserves_existing_values_when_fields_are_omitted(self) -> None:
        existing = UserProfileRecord(
            user_id="user-1",
            display_name="Codex Test",
            agent_style_name="",
            agent_style_prompt="",
            onboarding_completed=False,
        )

        with patch("app.application.user_data.service.get_user_profile_record", return_value=existing):
            with patch("app.application.user_data.service.save_user_profile_record") as save_profile:
                save_profile.side_effect = lambda _user_id, profile: profile

                updated = update_profile(
                    "user-1",
                    {
                        "display_name": None,
                        "agent_style_name": "",
                        "agent_style_prompt": "",
                        "onboarding_completed": True,
                    },
                )

        self.assertEqual(updated.display_name, "Codex Test")
        self.assertEqual(updated.agent_style_name, "")
        self.assertEqual(updated.agent_style_prompt, "")
        self.assertTrue(updated.onboarding_completed)


if __name__ == "__main__":
    unittest.main()
