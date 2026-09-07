"""
test_citability_score.py -- Tests the 0-100 AI-Citability Score.

The two properties a judge can check by hand are pinned here: the score is deterministic
(same findings in, same number out) and monotonic (adding a finding never raises it).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from scored import (
    MAX_CORROBORATION_CREDIT,
    SEVERITY_PENALTY,
    annotate_report,
    citability_score,
    compute_citability_score,
)
from compose_report import build_final_report


def finding(severity, title="Some finding", category="structured-data", **extra):
    f = {
        "id": "F-001",
        "title": title,
        "category": category,
        "severity": severity,
        "evidence": "Observed at https://acme.test/ via inspector: something concrete.",
        "suggested_action": {"summary": "s", "priority": severity, "how_to_fix": "h"},
    }
    f.update(extra)
    return f


def report(findings, **extra):
    r = {
        "site": "https://acme.test",
        "audited_at": "2026-01-01T00:00:00Z",
        "summary": {
            "total_findings": len(findings),
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "high": sum(1 for f in findings if f["severity"] == "high"),
            "medium": sum(1 for f in findings if f["severity"] == "medium"),
            "low": sum(1 for f in findings if f["severity"] == "low"),
        },
        "findings": findings,
    }
    r.update(extra)
    return r


class CitabilityScoreTests(unittest.TestCase):

    def test_clean_report_scores_100(self):
        self.assertEqual(citability_score(report([])), 100)

    def test_score_is_deterministic(self):
        r = report([finding("critical"), finding("medium"), finding("low")])
        scores = {citability_score(r) for _ in range(10)}
        self.assertEqual(len(scores), 1)
        self.assertEqual(compute_citability_score(r), compute_citability_score(r))

    def test_documented_arithmetic_matches(self):
        r = report([finding("critical"), finding("high"), finding("medium"), finding("low")])
        breakdown = compute_citability_score(r)
        self.assertEqual(breakdown["penalty"], 25 + 12 + 5 + 2)
        self.assertEqual(breakdown["score"], 100 - 44)
        self.assertEqual(breakdown["counted_findings"], 4)

    def test_reference_doc_worked_example(self):
        # citability-score.md documents: 1 high + 4 medium + 2 low, no corroboration signal
        #   penalty = (1 x 12) + (4 x 5) + (2 x 2) = 36  ->  score 64
        # This fixture mirrors the severity shape of the repo's own report.json.
        findings = (
            [finding("high")] + [finding("medium")] * 4 + [finding("low")] * 2
        )
        breakdown = compute_citability_score(report(findings))
        self.assertEqual(breakdown["penalty"], 36)
        self.assertEqual(breakdown["corroboration_credit"], 0)
        self.assertEqual(breakdown["score"], 64)
        self.assertEqual(
            breakdown["penalty_by_severity"],
            {"critical": 0, "high": 12, "medium": 20, "low": 4},
        )

    def test_adding_a_critical_finding_never_increases_the_score(self):
        base = [finding("low"), finding("medium"), finding("high")]
        for extra_count in range(1, 6):
            with_criticals = base + [finding("critical") for _ in range(extra_count)]
            previous = citability_score(report(base + [finding("critical")] * (extra_count - 1)))
            current = citability_score(report(with_criticals))
            self.assertLessEqual(current, previous)

    def test_monotonic_across_every_severity(self):
        base = report([finding("medium")])
        base_score = citability_score(base)
        for severity in SEVERITY_PENALTY:
            worse = report(base["findings"] + [finding(severity)])
            self.assertLess(citability_score(worse), base_score, severity)

    def test_score_floors_at_zero_and_stays_monotonic_there(self):
        many = [finding("critical") for _ in range(20)]
        self.assertEqual(citability_score(report(many)), 0)
        self.assertEqual(citability_score(report(many + [finding("critical")])), 0)

    def test_no_corroboration_signal_means_no_credit(self):
        r = report([finding("high")])
        self.assertEqual(compute_citability_score(r)["corroboration_credit"], 0)
        self.assertEqual(citability_score(r), 88)

    def test_corroboration_credit_only_from_recorded_signals(self):
        r = report(
            [finding("high")],
        )
        r["summary"]["corroboration_strengths"] = ["strong", "strong", "weak"]
        breakdown = compute_citability_score(r)
        self.assertEqual(breakdown["corroboration_credit"], 4)
        self.assertEqual(breakdown["score"], 100 - 12 + 4)

    def test_corroboration_credit_is_capped(self):
        r = report([finding("critical")])
        r["summary"]["corroboration_strengths"] = ["strong"] * 50
        self.assertEqual(
            compute_citability_score(r)["corroboration_credit"], MAX_CORROBORATION_CREDIT
        )

    def test_credit_from_finding_evidence_details(self):
        r = report(
            [finding("medium", evidence_details={"corroboration_strength": "strong"})]
        )
        self.assertEqual(compute_citability_score(r)["corroboration_credit"], 2)

    def test_unknown_severity_contributes_nothing(self):
        r = report([finding("medium")])
        r["findings"].append(dict(finding("medium"), severity="informational"))
        breakdown = compute_citability_score(r)
        self.assertEqual(breakdown["counted_findings"], 1)
        self.assertEqual(breakdown["penalty"], 5)

    def test_proactive_recommendations_do_not_change_the_score(self):
        findings = [finding("high")]
        without = citability_score(report(findings))
        with_recs = citability_score(
            report(
                findings,
                proactive_recommendations=[
                    {"title": "t", "rationale": "r",
                     "suggested_action": {"summary": "s", "priority": "low"}}
                ] * 5,
            )
        )
        self.assertEqual(without, with_recs)

    def test_annotate_report_writes_summary_field(self):
        r = report([finding("low")])
        annotate_report(r)
        self.assertEqual(r["summary"]["citability_score"], 98)

    def test_build_final_report_attaches_the_score(self):
        candidate = {
            "title": "Missing XML sitemap",
            "category": "crawlability",
            "severity": "medium",
            "evidence": "Observed at https://acme.test/sitemap.xml via http_probe: HTTP 404.",
            "source_skill": "crawl-render-audit",
            "fingerprint": "crawl:missing-sitemap",
            "suggested_action": {"summary": "s", "priority": "medium", "how_to_fix": "h"},
        }
        built = build_final_report("https://acme.test", [candidate])
        self.assertEqual(built["summary"]["citability_score"], 95)


if __name__ == "__main__":
    unittest.main()
