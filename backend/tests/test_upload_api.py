from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.interfaces.api.upload import _payload_int  # noqa: E402


class UploadApiPayloadTest(unittest.TestCase):
    def test_payload_int_preserves_zero_mapping_counts(self) -> None:
        payload = {
            "total_chunks": 3,
            "mapped_chunks": 0,
            "unmapped_chunks": 3,
        }

        self.assertEqual(_payload_int(payload, "mapped_chunks", payload["total_chunks"]), 0)
        self.assertEqual(_payload_int(payload, "unmapped_chunks"), 3)


if __name__ == "__main__":
    unittest.main()
