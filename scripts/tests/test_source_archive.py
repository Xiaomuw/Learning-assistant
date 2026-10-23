"""Verify actual Git archive behavior with synthetic files, never historical content."""
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SourceArchiveTest(unittest.TestCase):
    def test_reports_excluded_while_code_and_license_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", directory], check=True)
            (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            for name in ["LICENSE", "README.md", "backend/app/example.py",
                         "docs/test-reports/old-report.md", "docs/test-reports/screenshots/example.png",
                         "frontend/public/weapp-icons/NOTICE.txt"]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("original synthetic archive fixture\n")
            subprocess.run(["git", "-C", directory, "add", "."], check=True)
            tree = subprocess.check_output(["git", "-C", directory, "write-tree"], text=True).strip()
            archive = root / "source.tar"
            subprocess.run(["git", "-C", directory, "archive", "--format=tar", "--output", str(archive), tree], check=True)
            with tarfile.open(archive) as package:
                names = package.getnames()
            self.assertFalse(any(name.startswith("docs/test-reports") for name in names))
            for expected in ["LICENSE", "README.md", "backend/app/example.py", "frontend/public/weapp-icons/NOTICE.txt"]:
                self.assertIn(expected, names)
