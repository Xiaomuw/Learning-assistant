"""Ensure development Compose never publishes services to all network interfaces."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


class DevelopmentComposeSafetyTests(unittest.TestCase):
    def test_host_ports_explicitly_bind_loopback(self):
        text = COMPOSE.read_text(encoding="utf-8")
        matches = re.findall(r'^\s*-\s*"([^"]+)"\s*$', text, flags=re.MULTILINE)
        published = [x for x in matches if re.fullmatch(r"(?:[\d.]+:)?\d+:\d+(?:/(?:tcp|udp))?", x)]
        self.assertEqual(
            sorted(published),
            sorted(["127.0.0.1:5434:5432", "127.0.0.1:8003:8000", "127.0.0.1:3003:3000"]),
        )
        for item in published:
            with self.subTest(port=item):
                self.assertTrue(item.startswith("127.0.0.1:"), item)


if __name__ == "__main__":
    unittest.main()
