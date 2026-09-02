"""
test_compare_reports.py -- Tests the before/after report diff.

The fixtures are built so that every finding's destination bucket is known by hand:
  kept        -> in both reports, same severity        -> unchanged
  downgraded  -> in both, critical then medium         -> unchanged, severity improved
  fixed       -> only in the before report             -> resolved
  regression  -> only in the after report              -> new
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from compare_reports import SEVERITY_WEIGHT, compare_reports, match_key

SCRIPT = ROOT / "skills/audit-orchestrator/scripts/compare_reports.py"


def finding(fid, title, category, severity, fingerprint=None):
    f = {
        "id": fid,
        "title": title,
        "category": category,
        "severity": severity,
        "evidence": "Observed at https://acme.test/ via inspector: concrete observation.",
        "suggested_action": {"summary": "s", "priority": severity, "how_to_fix": "h"},
    }
    if fingerprint:
        f["fingerprint"] = fingerprint
    return f


def report(findings, audited_at, citability_score=None):
    summary = {
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f["severity"] == "critical"),
        "high": sum(1 for f in findings if f["severity"] == "high"),
        "medium": sum(1 for f in findings if f["severity"] == "medium"),
        "low": sum(1 for f in findings if f["severity"] == "low"),
    }
    if citability_score is not None:
        summary["citability_score"] = citability_score
    return {
        "site": "https://acme.test",
        "audited_at": audited_at,
        "summary": summary,
        "findings": findings,
    }


KEPT = finding("F-001", "Missing XML sitemap", "crawlability", "medium", "crawl:missing-sitemap")
FIXED = finding("F-002", "Missing Schema.org Organization data", "structured-data", "high",
                "schema:root-organization-missing")
DOWNGRADED_BEFORE = finding("F-003", "AI crawler disallowed", "crawlability", "critical",
                            "crawl:ai-agent-disallowed")
DOWNGRADED_AFTER = finding("F-002", "AI crawler disallowed", "crawlability", "medium",
                           "crawl:ai-agent-disallowed")
REGRESSION = finding("F-003", "Broken internal links in primary nav", "navigation", "low",
                     "engagement:broken-nav-links")

BEFORE = report([KEPT, FIXED, DOWNGRADED_BEFORE], "2026-01-01T00:00:00Z", citability_score=63)
AFTER = report([KEPT, DOWNGRADED_AFTER, REGRESSION], "2026-02-01T00:00:00Z", citability_score=88)


class CompareReportsTests(unittest.TestCase):

    def setUp(self):
        self.diff = compare_reports(BEFORE, AFTER)

    def test_resolved_bucket_holds_only_the_fixed_finding(self):
        self.assertEqual(
            [f["fingerprint"] for f in self.diff["resolved"]],
            ["schema:root-organization-missing"],
        )

    def test_new_bucket_holds_only_the_regression(self):
        self.assertEqual(
            [f["fingerprint"] for f in self.diff["new"]], ["engagement:broken-nav-links"]
        )

    def test_unchanged_bucket_holds_both_persisting_findings(self):
        self.assertEqual(
            sorted(f["fingerprint"] for f in self.diff["unchanged"]),
            ["crawl:ai-agent-disallowed", "crawl:missing-sitemap"],
        )

    def test_severity_change_is_noted_with_direction(self):
        by_fp = {f["fingerprint"]: f for f in self.diff["unchanged"]}
        downgraded = by_fp["crawl:ai-agent-disallowed"]
        self.assertTrue(downgraded["severity_changed"])
        self.assertEqual(downgraded["previous_severity"], "critical")
        self.assertEqual(downgraded["severity"], "medium")
        self.assertEqual(downgraded["severity_change"], "improved")
        self.assertFalse(by_fp["crawl:missing-sitemap"]["severity_changed"])

    def test_severity_worsening_is_labelled(self):
        worse = report(
            [finding("F-001", "Missing XML sitemap", "crawlability", "critical",
                     "crawl:missing-sitemap")],
            "2026-03-01T00:00:00Z",
        )
        base = report([KEPT], "2026-01-01T00:00:00Z")
        diff = compare_reports(base, worse)
        self.assertEqual(diff["unchanged"][0]["severity_change"], "worsened")
        self.assertEqual(diff["score_delta"], 2 - 4)

    def test_score_delta_is_weighted_and_positive_on_improvement(self):
        # before: medium(2) + high(3) + critical(4) = 9; after: medium(2) + medium(2) + low(1) = 5
        self.assertEqual(self.diff["before"]["weighted_severity_total"], 9)
        self.assertEqual(self.diff["after"]["weighted_severity_total"], 5)
        self.assertEqual(self.diff["score_delta"], 4)

    def test_score_delta_is_zero_for_identical_reports(self):
        self.assertEqual(compare_reports(BEFORE, BEFORE)["score_delta"], 0)
        identical = compare_reports(BEFORE, BEFORE)
        self.assertEqual(identical["resolved"], [])
        self.assertEqual(identical["new"], [])
        self.assertEqual(len(identical["unchanged"]), 3)

    def test_everything_resolved_gives_full_positive_delta(self):
        diff = compare_reports(BEFORE, report([], "2026-02-01T00:00:00Z"))
        self.assertEqual(len(diff["resolved"]), 3)
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["score_delta"], 9)

    def test_counts_summary_matches_buckets(self):
        self.assertEqual(
            self.diff["summary"],
            {
                "resolved_count": 1,
                "new_count": 1,
                "unchanged_count": 2,
                "severity_changed_count": 1,
                "no_changes": False,
            },
        )

    def test_identical_reports_are_flagged_as_no_changes(self):
        diff = compare_reports(BEFORE, BEFORE)
        self.assertTrue(diff["summary"]["no_changes"])
        self.assertFalse(self.diff["summary"]["no_changes"])

    def test_severity_only_change_is_not_no_changes(self):
        after = report(
            [finding("F-001", "Missing XML sitemap", "crawlability", "critical",
                     "crawl:missing-sitemap")],
            "2026-03-01T00:00:00Z",
        )
        diff = compare_reports(report([KEPT], "2026-01-01T00:00:00Z"), after)
        self.assertEqual(diff["summary"]["resolved_count"], 0)
        self.assertEqual(diff["summary"]["new_count"], 0)
        self.assertFalse(diff["summary"]["no_changes"])

    def test_same_site_detection(self):
        self.assertTrue(compare_reports(BEFORE, AFTER)["same_site"])
        other = report([], "2026-02-01T00:00:00Z")
        other["site"] = "https://different.test"
        self.assertFalse(compare_reports(BEFORE, other)["same_site"])

    def test_same_site_tolerates_trailing_slash_and_missing_metadata(self):
        slashed = report([], "2026-02-01T00:00:00Z")
        slashed["site"] = "https://acme.test/"
        self.assertTrue(compare_reports(BEFORE, slashed)["same_site"])
        bare = report([], "2026-02-01T00:00:00Z")
        del bare["site"]
        self.assertTrue(compare_reports(BEFORE, bare)["same_site"])

    def test_citability_score_delta_when_both_reports_carry_it(self):
        self.assertEqual(self.diff["citability_score_delta"], 25)

    def test_citability_score_delta_is_none_when_missing(self):
        stripped = json.loads(json.dumps(AFTER))
        del stripped["summary"]["citability_score"]
        self.assertIsNone(compare_reports(BEFORE, stripped)["citability_score_delta"])

    def test_falls_back_to_title_and_category_without_fingerprints(self):
        before = report(
            [finding("F-001", "Missing  XML   Sitemap!", "crawlability", "high")],
            "2026-01-01T00:00:00Z",
        )
        after = report(
            [finding("F-001", "missing xml sitemap", "crawlability", "low")],
            "2026-02-01T00:00:00Z",
        )
        diff = compare_reports(before, after)
        self.assertEqual(diff["resolved"], [])
        self.assertEqual(diff["new"], [])
        self.assertEqual(len(diff["unchanged"]), 1)
        self.assertEqual(diff["unchanged"][0]["severity_change"], "improved")

    def test_matches_when_fingerprint_missing_on_one_side_only(self):
        before = report(
            [finding("F-001", "Missing XML sitemap", "crawlability", "high",
                     "crawl:missing-sitemap")],
            "2026-01-01T00:00:00Z",
        )
        after = report(
            [finding("F-001", "Missing XML sitemap", "crawlability", "high")],
            "2026-02-01T00:00:00Z",
        )
        diff = compare_reports(before, after)
        self.assertEqual(diff["resolved"], [])
        self.assertEqual(diff["new"], [])
        self.assertEqual(len(diff["unchanged"]), 1)

    def test_same_title_in_different_categories_does_not_match(self):
        before = report(
            [finding("F-001", "Missing structured data", "structured-data", "high")],
            "2026-01-01T00:00:00Z",
        )
        after = report(
            [finding("F-001", "Missing structured data", "navigation", "high")],
            "2026-02-01T00:00:00Z",
        )
        diff = compare_reports(before, after)
        self.assertEqual(len(diff["resolved"]), 1)
        self.assertEqual(len(diff["new"]), 1)
        self.assertEqual(diff["unchanged"], [])

    def test_match_key_prefers_fingerprint(self):
        self.assertEqual(match_key(KEPT), ("fingerprint", "crawl:missing-sitemap"))
        self.assertEqual(
            match_key({"title": "A B!", "category": "navigation"}),
            ("title", "navigation|a b"),
        )

    def test_weights_are_the_documented_ladder(self):
        self.assertEqual(SEVERITY_WEIGHT, {"critical": 4, "high": 3, "medium": 2, "low": 1})

    def test_cli_writes_diff_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            before_path = Path(tmp) / "before.json"
            after_path = Path(tmp) / "after.json"
            out_path = Path(tmp) / "diff.json"
            before_path.write_text(json.dumps(BEFORE), encoding="utf-8")
            after_path.write_text(json.dumps(AFTER), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(before_path), str(after_path),
                 "--output", str(out_path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["score_delta"], 4)
            self.assertEqual(len(written["resolved"]), 1)
            self.assertEqual(json.loads(proc.stdout)["summary"]["new_count"], 1)


if __name__ == "__main__":
    unittest.main()
