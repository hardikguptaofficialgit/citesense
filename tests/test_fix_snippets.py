"""
test_fix_snippets.py -- Tests auto-generated JSON-LD fix snippets.

Covers the two guarantees that matter: a snippet is populated with the *real* observed
brand data when the audit has it, and no snippet is emitted at all when ground truth is
too sparse to fill the entity's identifying fields.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills/audit-orchestrator/scripts/fix_snippets.py"
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from fix_snippets import (
    PLACEHOLDER_PREFIX,
    attach_fix_snippets,
    explain_fix_snippet,
    generate_fix_snippet,
    snippet_type_for_finding,
)
from compose_report import build_final_report


def snippet_json(snippet):
    """Extracts and parses the JSON-LD payload out of a <script> block."""
    m = re.search(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', snippet, re.S
    )
    assert m, "snippet is not a well-formed JSON-LD script block"
    return json.loads(m.group(1))


ORG_FINDING = {
    "id": "F-001",
    "title": "Missing Schema.org Organization structured data on root landing page",
    "category": "structured-data",
    "severity": "medium",
    "evidence": "Observed at https://acme.test/ via jsonld_schema_extractor: 0 Organization blocks.",
    "fingerprint": "schema:root-organization-missing",
    "suggested_action": {
        "summary": "Add Organization JSON-LD markup to the homepage.",
        "priority": "medium",
        "how_to_fix": "Add a JSON-LD script declaring @type Organization.",
    },
    "evidence_details": {"url": "https://acme.test/"},
}

RICH_GROUND_TRUTH = {
    "brand_name": "Acme Robotics",
    "same_as": ["https://www.wikidata.org/wiki/Q12345"],
    "key_facts": {"founding_year": "1998", "email": "hello@acme.test"},
}

SPARSE_GROUND_TRUTH = {"brand_name": "Acme", "key_facts": {}}


class FixSnippetTests(unittest.TestCase):

    def test_organization_snippet_uses_real_brand_data(self):
        snippet = generate_fix_snippet(
            ORG_FINDING, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test"
        )
        self.assertIsNotNone(snippet)
        data = snippet_json(snippet)
        self.assertEqual(data["@type"], "Organization")
        self.assertEqual(data["name"], "Acme Robotics")
        self.assertFalse(data["name"].startswith(PLACEHOLDER_PREFIX))
        self.assertEqual(data["url"], "https://acme.test")
        self.assertEqual(data["foundingDate"], "1998")
        self.assertEqual(data["sameAs"], ["https://www.wikidata.org/wiki/Q12345"])
        # Genuinely unknown fields stay clearly marked rather than invented.
        self.assertTrue(data["logo"].startswith(PLACEHOLDER_PREFIX))

    def test_no_snippet_when_ground_truth_too_sparse(self):
        # Name + URL only is a bare template, not a fix.
        self.assertIsNone(
            generate_fix_snippet(
                ORG_FINDING, ground_truth=SPARSE_GROUND_TRUTH, site_url="https://acme.test"
            )
        )

    def test_no_snippet_without_any_ground_truth(self):
        self.assertIsNone(generate_fix_snippet(ORG_FINDING, ground_truth={}, site_url=""))

    def test_non_structured_data_findings_are_skipped(self):
        finding = dict(ORG_FINDING, category="crawlability")
        self.assertIsNone(snippet_type_for_finding(finding))
        self.assertIsNone(
            generate_fix_snippet(finding, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test")
        )

    def test_repair_findings_do_not_get_an_insert_snippet(self):
        # Malformed JSON-LD needs repair, not a fresh Organization block.
        finding = {
            "title": "Malformed JSON-LD structured data block",
            "category": "structured-data",
            "severity": "medium",
            "fingerprint": "schema:syntax-error:root",
            "suggested_action": {
                "summary": "Fix JSON-LD syntax errors.",
                "priority": "medium",
                "how_to_fix": "Validate the block.",
            },
        }
        self.assertIsNone(snippet_type_for_finding(finding))

    def test_meta_findings_are_not_mistaken_for_schema_types(self):
        for title, fingerprint in (
            ("Missing HTML document <title> tag", "meta:missing-title:/about/"),
            ("Missing meta description on key landing page", "meta:missing-description:/"),
        ):
            finding = {
                "title": title,
                "category": "structured-data",
                "severity": "medium",
                "fingerprint": fingerprint,
                "suggested_action": {"summary": "x", "priority": "medium", "how_to_fix": "y"},
            }
            self.assertIsNone(snippet_type_for_finding(finding), title)

    def test_product_snippet_uses_observed_page_name(self):
        finding = {
            "title": "Missing Schema.org Product and Offer structured data on commercial page",
            "category": "structured-data",
            "severity": "high",
            "evidence": "Observed at https://acme.test/pricing/ via jsonld_schema_extractor.",
            "fingerprint": "schema:product-offer-missing:/pricing/",
            "suggested_action": {"summary": "x", "priority": "high", "how_to_fix": "y"},
            "evidence_details": {"url": "https://acme.test/pricing/"},
        }
        pages = {
            "https://acme.test/pricing/": {
                "url": "https://acme.test/pricing/",
                "h1_texts": ["Acme Robotics Pro"],
                "meta_description": "Pro plan for industrial arms.",
            }
        }
        snippet = generate_fix_snippet(
            finding, ground_truth=RICH_GROUND_TRUTH, pages=pages, site_url="https://acme.test"
        )
        self.assertIsNotNone(snippet)
        data = snippet_json(snippet)
        self.assertEqual(data["name"], "Acme Robotics Pro")
        self.assertEqual(data["brand"]["name"], "Acme Robotics")
        # Price genuinely was not observed, so it must remain an explicit placeholder.
        self.assertTrue(data["offers"]["price"].startswith(PLACEHOLDER_PREFIX))

    def test_product_snippet_suppressed_without_page_snapshot(self):
        finding = {
            "title": "Missing Schema.org Product and Offer structured data on commercial page",
            "category": "structured-data",
            "severity": "high",
            "evidence": "Observed at https://acme.test/pricing/ via jsonld_schema_extractor.",
            "fingerprint": "schema:product-offer-missing:/pricing/",
            "suggested_action": {"summary": "x", "priority": "high", "how_to_fix": "y"},
            "evidence_details": {"url": "https://acme.test/pricing/"},
        }
        self.assertIsNone(
            generate_fix_snippet(finding, ground_truth=RICH_GROUND_TRUTH, pages={},
                                 site_url="https://acme.test")
        )

    def test_faqpage_questions_are_lifted_verbatim(self):
        finding = {
            "title": "Missing FAQPage structured data on help content",
            "category": "structured-data",
            "severity": "medium",
            "fingerprint": "schema:faqpage-missing:/help/",
            "suggested_action": {"summary": "x", "priority": "medium", "how_to_fix": "y"},
            "evidence_details": {"url": "https://acme.test/help/"},
        }
        pages = {
            "https://acme.test/help/": {
                "url": "https://acme.test/help/",
                "headings": [
                    {"level": 1, "text": "Help centre"},
                    {"level": 2, "text": "How do I reset my arm calibration?"},
                    {"level": 2, "text": "What is the warranty period?"},
                ],
            }
        }
        data = snippet_json(
            generate_fix_snippet(finding, ground_truth=RICH_GROUND_TRUTH, pages=pages,
                                 site_url="https://acme.test")
        )
        names = [q["name"] for q in data["mainEntity"]]
        self.assertEqual(
            names, ["How do I reset my arm calibration?", "What is the warranty period?"]
        )
        self.assertNotIn("Help centre", names)

    def test_breadcrumb_snippet_is_built_from_the_real_url_path(self):
        finding = {
            "title": "Missing BreadcrumbList structured data on deep page",
            "category": "structured-data",
            "severity": "low",
            "fingerprint": "schema:breadcrumblist-missing:/docs/api/",
            "suggested_action": {"summary": "x", "priority": "low", "how_to_fix": "y"},
            "evidence_details": {"url": "https://acme.test/docs/api/"},
        }
        data = snippet_json(
            generate_fix_snippet(finding, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test")
        )
        items = data["itemListElement"]
        self.assertEqual([i["position"] for i in items], [1, 2, 3])
        self.assertEqual(items[0]["name"], "Acme Robotics")
        self.assertEqual([i["name"] for i in items[1:]], ["Docs", "Api"])
        self.assertTrue(items[-1]["item"].endswith("/docs/api"))

    def test_attach_is_idempotent_and_counts_attachments(self):
        findings = [dict(ORG_FINDING, suggested_action=dict(ORG_FINDING["suggested_action"]))]
        first = attach_fix_snippets(
            findings, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test"
        )
        self.assertEqual(first, 1)
        snippet = findings[0]["suggested_action"]["fix_snippet"]
        second = attach_fix_snippets(
            findings, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test"
        )
        self.assertEqual(second, 0)
        self.assertEqual(findings[0]["suggested_action"]["fix_snippet"], snippet)

    def test_compose_report_wires_snippets_into_the_merge_step(self):
        candidate = {
            "title": "Missing Schema.org Organization structured data on root landing page",
            "category": "structured-data",
            "severity": "medium",
            "evidence": "Observed at https://acme.test/ via jsonld_schema_extractor: 0 blocks.",
            "source_skill": "crawl-render-audit",
            "fingerprint": "schema:root-organization-missing",
            "suggested_action": {
                "summary": "Add Organization JSON-LD markup to the homepage.",
                "priority": "medium",
                "how_to_fix": "Add a JSON-LD script declaring @type Organization.",
            },
        }
        report = build_final_report(
            "https://acme.test", [candidate], ground_truth=RICH_GROUND_TRUTH
        )
        self.assertIn("fix_snippet", report["findings"][0]["suggested_action"])
        self.assertEqual(
            snippet_json(report["findings"][0]["suggested_action"]["fix_snippet"])["name"],
            "Acme Robotics",
        )

    def test_compose_report_omits_snippets_without_ground_truth(self):
        candidate = {
            "title": "Missing Schema.org Organization structured data on root landing page",
            "category": "structured-data",
            "severity": "medium",
            "evidence": "Observed at https://acme.test/ via jsonld_schema_extractor: 0 blocks.",
            "source_skill": "crawl-render-audit",
            "fingerprint": "schema:root-organization-missing",
            "suggested_action": {
                "summary": "Add Organization JSON-LD markup to the homepage.",
                "priority": "medium",
                "how_to_fix": "Add a JSON-LD script declaring @type Organization.",
            },
        }
        report = build_final_report("https://acme.test", [candidate])
        self.assertNotIn("fix_snippet", report["findings"][0]["suggested_action"])


class ExplainAndCliTests(unittest.TestCase):
    """The CLI must make a suppressed snippet visibly a refusal to guess, not a silent no-op."""

    def test_explain_reports_missing_ground_truth(self):
        result = explain_fix_snippet(ORG_FINDING, ground_truth=None, site_url="https://acme.test")
        self.assertEqual(result["schema_type"], "Organization")
        self.assertFalse(result["emitted"])
        self.assertIn("no ground_truth supplied", result["reason"])
        self.assertIsNone(result["snippet"])

    def test_explain_reports_missing_page_snapshot_for_product(self):
        finding = {
            "id": "F-002",
            "title": "Missing Schema.org Product and Offer structured data on commercial page",
            "category": "structured-data",
            "severity": "high",
            "fingerprint": "schema:product-offer-missing:/pricing/",
            "suggested_action": {"summary": "x", "priority": "high", "how_to_fix": "y"},
            "evidence_details": {"url": "https://acme.test/pricing/"},
        }
        result = explain_fix_snippet(
            finding, ground_truth=RICH_GROUND_TRUTH, pages={}, site_url="https://acme.test"
        )
        self.assertFalse(result["emitted"])
        self.assertIn("refusing to invent", result["reason"])

    def test_explain_counts_real_and_placeholder_values_on_success(self):
        result = explain_fix_snippet(
            ORG_FINDING, ground_truth=RICH_GROUND_TRUTH, site_url="https://acme.test"
        )
        self.assertTrue(result["emitted"])
        self.assertIn("real values", result["reason"])
        self.assertIsNotNone(result["snippet"])

    def test_explain_marks_non_candidates(self):
        result = explain_fix_snippet(dict(ORG_FINDING, category="crawlability"))
        self.assertIsNone(result["schema_type"])
        self.assertFalse(result["emitted"])
        self.assertIn("not a structured-data finding", result["reason"])

    def _report_with_org_finding(self):
        return {
            "site": "https://acme.test",
            "audited_at": "2026-01-01T00:00:00Z",
            "summary": {"total_findings": 1, "critical": 0, "high": 0, "medium": 1, "low": 0},
            "findings": [json.loads(json.dumps(ORG_FINDING))],
        }

    def test_cli_emits_nothing_without_inventory_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(self._report_with_org_finding()), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout.split("\n--- ")[0])
            self.assertEqual(payload["snippet_candidates"], 1)
            self.assertEqual(payload["snippets_emitted"], 0)
            self.assertFalse(payload["ground_truth_supplied"])
            self.assertIn("no ground_truth supplied", payload["candidates"][0]["reason"])

    def test_cli_emits_real_snippet_with_inventory_and_writes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            inv_path = Path(tmp) / "inventory.json"
            out_path = Path(tmp) / "annotated.json"
            report_path.write_text(json.dumps(self._report_with_org_finding()), encoding="utf-8")
            inv_path.write_text(
                json.dumps({"ground_truth": RICH_GROUND_TRUTH, "pages": {}}), encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(report_path),
                 "--inventory", str(inv_path), "--output", str(out_path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout.split("\n--- ")[0])
            self.assertEqual(payload["snippets_emitted"], 1)
            self.assertTrue(payload["ground_truth_supplied"])

            written = json.loads(out_path.read_text(encoding="utf-8"))
            snippet = written["findings"][0]["suggested_action"]["fix_snippet"]
            self.assertEqual(snippet_json(snippet)["name"], "Acme Robotics")

    def test_cli_accepts_a_bare_ground_truth_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            gt_path = Path(tmp) / "gt.json"
            report_path.write_text(json.dumps(self._report_with_org_finding()), encoding="utf-8")
            gt_path.write_text(json.dumps(RICH_GROUND_TRUTH), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(report_path), "--inventory", str(gt_path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                json.loads(proc.stdout.split("\n--- ")[0])["snippets_emitted"], 1
            )


if __name__ == "__main__":
    unittest.main()
