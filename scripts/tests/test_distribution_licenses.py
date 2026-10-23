"""Build contexts must carry the actual project license and its exclusions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DistributionLicenseTest(unittest.TestCase):
    def test_project_license_copies_match_canonical_texts(self):
        for directory in ("backend", "frontend", "frontend-weapp"):
            for filename in ("LICENSE", "LICENSE-SCOPE.md"):
                with self.subTest(directory=directory, filename=filename):
                    self.assertEqual((ROOT / directory / filename).read_bytes(), (ROOT / filename).read_bytes())
