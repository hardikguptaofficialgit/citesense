"""
test_report_io.py -- Tests shared CLI I/O behaviour for the report-consuming scripts.

Covers the failure modes a judge or teammate hits first: a bad path, a malformed report,
and an --output path whose directory does not exist yet. All three must produce a readable
one-line message and a non-zero exit code, never a raw traceback.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills/audit-orchestrator/scripts"
sys.path.insert(0, str(SCRIPTS))

from report_io import ReportIOError, load_report, write_text

VALID_REPORT = {
    "site": "https://acme.test",
    "audited_at": "2026-01-01T00:00:00Z",
    "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
    "findings": [],
}

CLIS = ("render_dashboard.py", "compare_reports.py", "scored.py", "fix_snippets.py")


def run(script, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)] + list(args),
        capture_output=True, text=True, timeout=60,
    )


class ReportIOTests(unittest.TestCase):

    def test_load_report_rejects_missing_file(self):
        with self.assertRaises(ReportIOError) as ctx:
            load_report("no-such-file.json")
        self.assertIn("not found", str(ctx.exception))

    def test_load_report_rejects_malformed_json_with_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"site": "x", broken', encoding="utf-8")
            with self.assertRaises(ReportIOError) as ctx:
                load_report(str(bad))
            message = str(ctx.exception)
            self.assertIn("not valid JSON", message)
            self.assertIn("line 1", message)
            self.assertIn(str(bad), message)

    def test_load_report_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            listy = Path(tmp) / "list.json"
            listy.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ReportIOError) as ctx:
                load_report(str(listy))
            self.assertIn("must be a JSON object", str(ctx.exception))

    def test_load_report_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            bom = Path(tmp) / "bom.json"
            bom.write_text(json.dumps(VALID_REPORT), encoding="utf-8-sig")
            self.assertEqual(load_report(str(bom))["site"], "https://acme.test")

    def test_write_text_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "deep" / "nested" / "out.html"
            write_text(str(target), "<p>hi</p>")
            self.assertEqual(target.read_text(encoding="utf-8"), "<p>hi</p>")

    def test_write_text_to_bare_filename_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.html"
            write_text(str(target), "x")
            self.assertTrue(target.exists())


class CliErrorHandlingTests(unittest.TestCase):
    """Every report-consuming CLI must fail readably, not with a traceback."""

    def _assert_clean_failure(self, proc):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("error:", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_input_file_fails_cleanly(self):
        for script in CLIS:
            args = ["no-such-file.json"]
            if script == "compare_reports.py":
                args.append("no-such-file-2.json")
            with self.subTest(script=script):
                self._assert_clean_failure(run(script, *args))

    def test_malformed_input_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            good = Path(tmp) / "good.json"
            bad.write_text('{"site": "x", broken', encoding="utf-8")
            good.write_text(json.dumps(VALID_REPORT), encoding="utf-8")
            for script in CLIS:
                args = [str(bad)]
                if script == "compare_reports.py":
                    args.append(str(good))
                with self.subTest(script=script):
                    proc = run(script, *args)
                    self._assert_clean_failure(proc)
                    self.assertIn("not valid JSON", proc.stderr)

    def test_output_into_missing_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps(VALID_REPORT), encoding="utf-8")
            target = Path(tmp) / "does" / "not" / "exist" / "dashboard.html"
            proc = run("render_dashboard.py", str(report_path), "--output", str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(target.exists())

    def test_compare_output_into_missing_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps(VALID_REPORT), encoding="utf-8")
            target = Path(tmp) / "new" / "diff.json"
            proc = run("compare_reports.py", str(report_path), str(report_path),
                       "--output", str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(target.exists())

    def test_compare_warns_when_sites_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text(json.dumps(VALID_REPORT), encoding="utf-8")
            other = dict(VALID_REPORT, site="https://different.test")
            b.write_text(json.dumps(other), encoding="utf-8")
            proc = run("compare_reports.py", str(a), str(b))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("warning: comparing two different sites", proc.stderr)

    def test_compare_does_not_warn_for_the_same_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            a.write_text(json.dumps(VALID_REPORT), encoding="utf-8")
            proc = run("compare_reports.py", str(a), str(a))
            self.assertNotIn("warning", proc.stderr)


if __name__ == "__main__":
    unittest.main()
