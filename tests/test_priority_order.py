"""
test_priority_order.py -- Tests the effort model and the top-level priority_fix_order ranking.

Pinned here: effort is explicit-but-defaulted (a declared rung wins, otherwise the category
default from models.CATEGORY_DEFAULT_EFFORT); impact dominates the ranking and effort only
breaks ties within an impact tier; the order is deterministic regardless of input order; and
the new fields are optional, so a report carrying them still validates against the schema.
"""
import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "audit-orchestrator"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from models import (
    CATEGORY_DEFAULT_EFFORT, EFFORT_LEVELS, VALID_CATEGORIES,
    CandidateFinding, create_candidate_finding, resolve_effort,
)
from priority_order import MAX_PRIORITY_FIXES, build_rationale, rank_priority_fixes
from compose_report import build_final_report
from render_dashboard import render_dashboard

SCRIPT = ROOT / "skills/audit-orchestrator/scripts/priority_order.py"
SCHEMA = json.loads(
    (ROOT / "skills/audit-orchestrator/references/report-schema.json").read_text(encoding="utf-8")
)


def finding(fid, impact, category="structured-data", severity=None, **extra):
    severity = severity or impact
    f = {
        "id": fid,
        "title": f"Finding {fid}",
        "category": category,
        "severity": severity,
        "impact": impact,
        "evidence": "Observed at https://acme.test/ via inspector: something concrete.",
        "suggested_action": {"summary": "s", "priority": severity, "how_to_fix": "h"},
    }
    f.update(extra)
    return f


def candidate(category="structured-data", **extra):
    return create_candidate_finding(
        title="Missing Organization schema",
        category=category,
        severity="high",
        url="https://acme.test/",
        observation="No Organization JSON-LD on the homepage.",
        method="jsonld_extractor",
        source_skill="crawl-render-audit",
        action_summary="Add Organization JSON-LD.",
        action_priority="high",
        action_how_to_fix="Add a JSON-LD script declaring @type Organization.",
        **extra,
    )


def validate(instance, schema, path="$"):
    """
    Minimal stdlib validator for the draft-07 keywords report-schema.json uses
    (type, required, properties, items, enum, pattern, minimum, maximum, maxItems).
    Returns a list of error strings; empty means valid.
    """
    errors = []
    types = schema.get("type")
    if types is not None:
        py = {"object": dict, "array": list, "string": str, "integer": int,
              "boolean": bool, "null": type(None)}
        allowed = types if isinstance(types, list) else [types]
        ok = any(
            isinstance(instance, py[t]) and not (t == "integer" and isinstance(instance, bool))
            for t in allowed
        )
        if not ok:
            return [f"{path}: expected {allowed}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, str) and "pattern" in schema and not re.search(schema["pattern"], instance):
        errors.append(f"{path}: {instance!r} does not match {schema['pattern']}")
    if isinstance(instance, int) and "minimum" in schema and instance < schema["minimum"]:
        errors.append(f"{path}: below minimum")
    if isinstance(instance, int) and "maximum" in schema and instance > schema["maximum"]:
        errors.append(f"{path}: above maximum")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate(instance[key], sub, f"{path}.{key}"))
    if isinstance(instance, list):
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors


class EffortModelTests(unittest.TestCase):

    def test_every_category_has_a_default_effort(self):
        self.assertEqual(set(CATEGORY_DEFAULT_EFFORT), VALID_CATEGORIES)
        self.assertTrue(set(CATEGORY_DEFAULT_EFFORT.values()) <= set(EFFORT_LEVELS))

    def test_effort_defaults_from_category_when_not_declared(self):
        self.assertEqual(candidate("structured-data").effort, "trivial")
        self.assertEqual(candidate("navigation").effort, "moderate")
        self.assertEqual(candidate("corroboration").effort, "involved")

    def test_explicit_effort_overrides_category_default(self):
        f = candidate("structured-data", effort="involved")
        self.assertEqual(f.effort, "involved")
        self.assertEqual(f.to_dict()["effort"], "involved")

    def test_invalid_declared_effort_falls_back_to_category_default(self):
        f = CandidateFinding(
            title="t", category="freshness", severity="low", evidence="e",
            source_skill="s", suggested_action={}, effort="enormous",
        )
        self.assertEqual(f.effort, "trivial")

    def test_to_dict_carries_effort(self):
        self.assertEqual(candidate("render-gap").to_dict()["effort"], "involved")

    def test_unknown_category_gets_no_guessed_effort(self):
        self.assertIsNone(resolve_effort("not-a-category"))
        self.assertEqual(resolve_effort("not-a-category", "moderate"), "moderate")


class RankingTests(unittest.TestCase):

    def test_high_trivial_ranks_above_high_involved_and_medium_trivial(self):
        findings = [
            finding("F-001", "medium", category="structured-data"),  # medium / trivial
            finding("F-002", "high", category="corroboration"),      # high / involved
            finding("F-003", "high", category="structured-data"),    # high / trivial
        ]
        self.assertEqual([r["id"] for r in rank_priority_fixes(findings)], ["F-003", "F-002", "F-001"])

    def test_severity_breaks_ties_when_impact_and_effort_match(self):
        findings = [
            finding("F-001", "high", severity="low"),
            finding("F-002", "high", severity="critical"),
        ]
        self.assertEqual([r["id"] for r in rank_priority_fixes(findings)], ["F-002", "F-001"])

    def test_explicit_effort_on_dict_is_used_over_category_default(self):
        findings = [
            finding("F-001", "high", category="structured-data", effort="involved"),
            finding("F-002", "high", category="corroboration", effort="trivial"),
        ]
        ranked = rank_priority_fixes(findings)
        self.assertEqual([r["id"] for r in ranked], ["F-002", "F-001"])
        self.assertEqual(ranked[0]["effort"], "trivial")

    def test_missing_impact_falls_back_to_severity(self):
        f = finding("F-001", "high")
        del f["impact"]
        self.assertEqual(rank_priority_fixes([f])[0]["impact"], "high")

    def test_entry_shape_and_rationale(self):
        entry = rank_priority_fixes([finding("F-001", "high")])[0]
        self.assertEqual(set(entry), {"id", "title", "severity", "impact", "effort", "rationale"})
        self.assertEqual(entry["rationale"], "High impact, trivial fix — best return for effort.")
        self.assertIn("not classified", build_rationale("low", None))

    def test_returns_at_most_five(self):
        findings = [finding(f"F-{i:03d}", "medium") for i in range(1, 9)]
        self.assertEqual(len(rank_priority_fixes(findings)), MAX_PRIORITY_FIXES)
        self.assertEqual(MAX_PRIORITY_FIXES, 5)

    def test_returns_all_when_fewer_than_five(self):
        self.assertEqual(len(rank_priority_fixes([finding("F-001", "low"), finding("F-002", "high")])), 2)

    def test_returns_empty_for_no_findings(self):
        self.assertEqual(rank_priority_fixes([]), [])
        self.assertEqual(rank_priority_fixes(None), [])

    def test_shuffled_input_yields_identical_order(self):
        impacts = ["critical", "high", "medium", "low"]
        categories = ["structured-data", "navigation", "corroboration", "not-a-category"]
        findings = [
            finding(f"F-{i:03d}", impacts[i % 4], category=categories[(i * 3) % 4],
                    severity=impacts[(i * 7) % 4])
            for i in range(1, 21)
        ]
        expected = rank_priority_fixes(findings)
        rng = random.Random(1234)
        for _ in range(25):
            shuffled = list(findings)
            rng.shuffle(shuffled)
            self.assertEqual(rank_priority_fixes(shuffled), expected)

    def test_input_list_is_not_modified(self):
        findings = [finding("F-002", "low"), finding("F-001", "high")]
        snapshot = json.dumps(findings, sort_keys=True)
        rank_priority_fixes(findings)
        self.assertEqual(json.dumps(findings, sort_keys=True), snapshot)


class ReportWiringTests(unittest.TestCase):

    def test_build_final_report_attaches_priority_fix_order(self):
        report = build_final_report("https://acme.test", [
            finding("X", "medium", category="structured-data", title="Medium trivial"),
            finding("X", "high", category="render-gap", title="High involved"),
        ])
        order = report["priority_fix_order"]
        self.assertEqual([r["title"] for r in order], ["High involved", "Medium trivial"])
        ids = {f["id"] for f in report["findings"]}
        self.assertTrue(all(r["id"] in ids for r in order))
        self.assertNotIn("priority_fix_order", report["summary"])

    def test_build_final_report_omits_priority_fix_order_for_empty_findings(self):
        self.assertNotIn("priority_fix_order", build_final_report("https://acme.test", []))

    def test_priority_fix_order_is_optional_in_schema(self):
        self.assertNotIn("priority_fix_order", SCHEMA["required"])
        self.assertIn("priority_fix_order", SCHEMA["properties"])
        finding_schema = SCHEMA["properties"]["findings"]["items"]
        self.assertIn("effort", finding_schema["properties"])
        self.assertNotIn("effort", finding_schema["required"])

    def test_report_with_priority_and_effort_fields_validates(self):
        findings = [candidate(c).to_dict() for c in ("structured-data", "navigation", "corroboration")]
        report = build_final_report("https://acme.test", findings)
        self.assertIn("priority_fix_order", report)
        self.assertTrue(all("effort" in f for f in report["findings"]))
        self.assertEqual(validate(report, SCHEMA), [])

    def test_report_without_new_fields_still_validates(self):
        report = build_final_report("https://acme.test", [finding("X", "high")])
        del report["priority_fix_order"]
        self.assertEqual(validate(report, SCHEMA), [])

    def test_validator_rejects_a_bad_effort(self):
        report = build_final_report("https://acme.test", [finding("X", "high", effort="trivial")])
        report["findings"][0]["effort"] = "enormous"
        self.assertTrue(validate(report, SCHEMA))

    def test_cli_recomputes_order_for_existing_report(self):
        report = build_final_report("https://acme.test", [finding("X", "high")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["priority_fix_order"], report["priority_fix_order"])


class DashboardPriorityTests(unittest.TestCase):

    def _report(self):
        return build_final_report("https://acme.test", [
            finding("X", "high", category="structured-data", title="Add Organization schema"),
            finding("X", "medium", category="navigation", title="Primary nav lacks labels"),
        ])

    def test_section_rendered_above_findings_when_present(self):
        html = render_dashboard(self._report())
        self.assertIn("Priority fixes: do these first", html)
        self.assertLess(html.index("Priority fixes: do these first"), html.index("<h2>Findings</h2>"))
        self.assertIn("effort: trivial", html)
        self.assertIn("best return for effort.", html)

    def test_section_skipped_when_absent_or_empty(self):
        report = self._report()
        del report["priority_fix_order"]
        self.assertNotIn("Priority fixes", render_dashboard(report))
        report["priority_fix_order"] = []
        self.assertNotIn("Priority fixes", render_dashboard(report))

    def test_priority_strings_are_escaped(self):
        report = self._report()
        report["priority_fix_order"][0]["title"] = "<img src=x onerror=alert(1)>"
        report["priority_fix_order"][0]["rationale"] = "<script>alert(2)</script>"
        html = render_dashboard(report)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("<script>alert(2)", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)


if __name__ == "__main__":
    unittest.main()
