"""Check source provenance and the client assets shipped by the icon renderer."""

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/navigation-icons"
DESTINATIONS = [ROOT / "frontend/public/weapp-icons", ROOT / "frontend-weapp/src/assets/icons"]


class NavigationAssetTests(unittest.TestCase):
    def test_pngs_match_reviewed_sources_and_both_clients(self) -> None:
        manifest = json.loads((SOURCE / "manifest.json").read_text())
        self.assertEqual(len(manifest["icons"]), 8)
        self.assertEqual(len({item["file"] for item in manifest["icons"]}), 8)
        for item in manifest["icons"]:
            with self.subTest(file=item["file"]):
                source = (SOURCE / item["source"]).read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), item["source_sha256"])
                copies = [(directory / item["file"]).read_bytes() for directory in DESTINATIONS]
                self.assertEqual(copies[0], copies[1])
                self.assertEqual(hashlib.sha256(copies[0]).hexdigest(), item["png_sha256"])
                self.assertEqual(copies[0][:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", copies[0][16:24]), (81, 81))
                self.assertLess(len(copies[0]), 40 * 1024)
        for directory in DESTINATIONS:
            self.assertEqual({p.name for p in directory.glob("*.png")},
                             {item["file"] for item in manifest["icons"]})

    def test_both_notices_retain_complete_upstream_license_texts(self) -> None:
        notices = [(directory / "NOTICE.txt").read_text() for directory in DESTINATIONS]
        self.assertEqual(notices[0], notices[1])
        for name in ("LUCIDE-LICENSE", "FEATHER-LICENSE"):
            self.assertIn((SOURCE / name).read_text(), notices[0])
        self.assertIn("rasterization to 81x81", notices[0])


if __name__ == "__main__":
    unittest.main()
