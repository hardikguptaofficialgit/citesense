import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))


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
        self.assertIn("CiteSense website AI-readiness auditor", result.stdout)
        self.assertIn("audit", result.stdout)
        self.assertIn("batch", result.stdout)

    def test_subcommand_help_is_agent_friendly(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        for command, expected in (
            (["audit", "--help"], "Public http(s) URL"),
            (["batch", "--help"], "one public http(s) URL per line"),
        ):
            result = subprocess.run(
                [sys.executable, "-m", "citesense", *command],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertIn("read-only", result.stdout.lower() + result.stderr.lower())

    def test_audit_command_writes_engine_report(self):
        from citesense import cli

        report = {"site": "https://example.test", "summary": {"total_findings": 0}, "findings": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "run_full_audit", return_value=report) as audit:
            output = Path(directory) / "nested" / "report.json"
            code = cli.main(["audit", "https://example.test", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.read_text()), report)
            audit.assert_called_once_with(
                "https://example.test",
                max_pages=5,
                timeout=8,
                save_inventory_path=None,
                external_evidence=None,
            )

    def test_audit_rejects_invalid_url_without_running_engine(self):
        from citesense import cli

        with patch.object(cli, "run_full_audit") as audit:
            self.assertEqual(cli.main(["audit", "not-a-url"]), 2)
            audit.assert_not_called()

    def test_legacy_url_first_invocation_is_preserved(self):
        from citesense import cli

        report = {"site": "https://example.test", "summary": {}, "findings": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "run_full_audit", return_value=report):
            self.assertEqual(cli.main(["https://example.test", "-o", str(Path(directory) / "report.json")]), 0)

    def test_batch_deduplicates_blank_lines_writes_reports_and_continues(self):
        from citesense import cli

        reports = {
            "https://example.test": {"site": "https://example.test", "summary": {"total_findings": 1}},
            "https://second.test": {"site": "https://second.test", "summary": {"total_findings": 0}},
        }

        def fake_audit(url, **kwargs):
            if url == "https://broken.test":
                raise RuntimeError("simulated failure")
            return reports[url]

        with tempfile.TemporaryDirectory() as directory, patch.object(cli, "run_full_audit", side_effect=fake_audit) as audit:
            source = Path(directory) / "websites.txt"
            source.write_text(
                "\nhttps://example.test\nhttps://example.test\nbad-url\nhttps://broken.test\nhttps://second.test\n",
                encoding="utf-8",
            )
            output_dir = Path(directory) / "reports"
            with patch("sys.stdout") as stdout:
                code = cli.main(["batch", str(source), "--output-dir", str(output_dir)])
            summary = json.loads("".join(call.args[0] for call in stdout.write.call_args_list))
            self.assertTrue((output_dir / "example_test.json").exists())
            self.assertTrue((output_dir / "second_test.json").exists())

        self.assertEqual(code, 1)
        self.assertEqual(summary["requested"], 4)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["failed"], 2)
        self.assertEqual(audit.call_count, 3)


if __name__ == "__main__":
    unittest.main()
