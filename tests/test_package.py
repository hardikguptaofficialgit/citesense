import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def test_public_api_imports_existing_orchestrator(self):
        sys.path.insert(0, str(ROOT / "src"))
        from citesense import run_full_audit

        self.assertTrue(callable(run_full_audit))

    def test_module_cli_help(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, "-m", "citesense", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Brand AI-Readiness Audit Orchestrator", result.stdout)


if __name__ == "__main__":
    unittest.main()
