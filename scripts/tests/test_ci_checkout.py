"""Exercise the credential check using disposable Git repositories and fake values."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "check_ci_checkout.py"
spec = importlib.util.spec_from_file_location("check_ci_checkout", SCRIPT)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CheckoutCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repository = Path(directory.name)

    def initialize(self) -> None:
        subprocess.run(["git", "init", "--quiet", str(self.repository)], check=True, capture_output=True)

    def inspect(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = checker.check_checkout(self.repository)
        return code, output.getvalue()

    def test_clean_checkout_passes(self) -> None:
        self.initialize()
        self.assertEqual(self.inspect()[0], 0)

    def test_persisted_header_fails_without_disclosing_value(self) -> None:
        self.initialize()
        fake_header = "AUTHORIZATION: basic synthetic-ci-test-only"
        for key in ("http.https://github.com/.extraheader", "http.extraheader"):
            with self.subTest(key=key):
                subprocess.run(
                    ["git", "config", "--local", key, fake_header],
                    cwd=self.repository, check=True, capture_output=True,
                )
                code, output = self.inspect()
                self.assertEqual(code, 1)
                self.assertNotIn(fake_header, output)
                self.assertNotIn("synthetic-ci-test-only", output)
                self.assertIn("values withheld", output)
                subprocess.run(
                    ["git", "config", "--local", "--unset-all", key],
                    cwd=self.repository, check=True, capture_output=True,
                )

    def test_inspection_failure_does_not_pass(self) -> None:
        code, output = self.inspect()
        self.assertEqual(code, 1)
        self.assertIn("could not inspect", output)


if __name__ == "__main__":
    unittest.main()
