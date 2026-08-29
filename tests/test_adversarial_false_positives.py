"""
test_adversarial_false_positives.py -- Adversarial tests to verify the audit system
does NOT emit false positive findings for common real-world edge cases.
"""
import unittest
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/crawl-render-audit/scripts"))
sys.path.insert(0, str(ROOT / "skills/freshness-corroboration/scripts"))
sys.path.insert(0, str(ROOT / "skills/engagement-audit/scripts"))
sys.path.insert(0, str(ROOT / "skills/trust-corroboration-graph/scripts"))
sys.path.insert(0, str(ROOT / "skills/citation-simulator/scripts"))
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from site_inventory import SiteInventory, analyze_page_html
from crawlability_check import evaluate_crawlability
from render_and_data_scan import evaluate_render_and_data_scan, evaluate_page_render_and_data
from freshness_and_consistency_scan import evaluate_freshness_and_consistency
from engagement_scan import evaluate_engagement_audit, evaluate_page_engagement, check_broken_links_sample
from corroboration_scorer import assess_collision_risk, score_fact
from compose_report import dedupe, compute_summary, build_final_report


class AdversarialFalsePositiveTests(unittest.TestCase):

    def test_no_false_positive_for_missing_datemodified_on_static_pages(self):
        """Missing dateModified alone must NOT produce a freshness defect finding."""
        inv = SiteInventory("https://example.com")
        html = "<html><head><title>Company Home</title></head><body><h1>Welcome</h1><p>Our core services.</p></body></html>"
        snap = analyze_page_html("https://example.com", html, "https://example.com", 200, 0.2)
        inv.pages["https://example.com"] = snap

        findings = evaluate_freshness_and_consistency(inv)
        freshness_defects = [f for f in findings if f["category"] == "freshness"]
        self.assertEqual(len(freshness_defects), 0, "Missing dateModified must not produce a freshness defect finding")

    def test_no_false_positive_for_breadcrumbs_on_shallow_or_root_pages(self):
        """Root pages and shallow 1-level paths must not be flagged for missing breadcrumbs."""
        html = "<html><head><title>Home</title></head><body><h1>Homepage</h1><a href='/about'>About</a><a href='/pricing'>Pricing</a><button>Get Started</button></body></html>"
        snap = analyze_page_html("https://example.com", html, "https://example.com", 200, 0.1)
        findings = evaluate_page_engagement(snap, is_root=True)
        breadcrumb_findings = [f for f in findings if "breadcrumb" in f["title"].lower()]
        self.assertEqual(len(breadcrumb_findings), 0, "Root page must not be flagged for missing breadcrumbs")

        shallow_html = "<html><head><title>About</title></head><body><h1>About Us</h1><a href='/'>Home</a><button>Contact</button></body></html>"
        shallow_snap = analyze_page_html("https://example.com/about", shallow_html, "https://example.com/about", 200, 0.1)
        shallow_findings = evaluate_page_engagement(shallow_snap, is_root=False)
        shallow_breadcrumb = [f for f in shallow_findings if "breadcrumb" in f["title"].lower()]
        self.assertEqual(len(shallow_breadcrumb), 0, "Shallow path /about must not be flagged for missing breadcrumbs")

    def test_no_false_positive_for_js_usage_when_facts_exist_in_raw_html(self):
        """Using JavaScript frameworks is not a defect if raw HTML contains readable text and facts."""
        html = """
        <html>
        <head><title>Acme Widgets - Premium Tools</title></head>
        <body>
            <h1>Acme Widgets</h1>
            <p>We provide enterprise cloud security starting at $49/month. Contact support@acme.com.</p>
            <script src="/static/app.bundle.js"></script>
        </body>
        </html>
        """
        snap = analyze_page_html("https://example.com/product", html, "https://example.com/product", 200, 0.1)
        findings = evaluate_page_render_and_data(snap, is_root=False)
        render_gap_findings = [f for f in findings if f["category"] == "render-gap"]
        self.assertEqual(len(render_gap_findings), 0, "Raw HTML containing visible facts must not trigger render-gap finding")

    def test_no_false_positive_for_entity_collision_when_sameas_present(self):
        """Entity collisions with disambiguating sameAs markers or different industry must not be high risk."""
        # Case 1: Unrelated industry collision
        unrelated = assess_collision_risk([{"domain": "acme-plumbing.test", "same_or_adjacent_industry": False}], {})
        self.assertEqual(unrelated["risk"], "none_detected")

        # Case 2: Same industry but has disambiguating markers
        markers = {"same_as_wikidata": True, "same_as_wikipedia": True, "org_schema": True}
        disambiguated = assess_collision_risk([{"domain": "acme-tech.test", "same_or_adjacent_industry": True}], markers)
        self.assertEqual(disambiguated["risk"], "low", "Disambiguated collision must be low risk")

    def test_button_and_form_recognition_prevents_false_cta_findings(self):
        """Pages with <button>, role='button', or <form> must not be falsely flagged for missing CTA."""
        html = """
        <html>
        <head><title>Product Pricing</title></head>
        <body>
            <h1>Pro Plan</h1>
            <p>Best for scaling teams.</p>
            <form action='/checkout' method='POST'>
                <input type='hidden' name='plan' value='pro'/>
                <button type='submit'>Subscribe Now</button>
            </form>
        </body>
        </html>
        """
        snap = analyze_page_html("https://example.com/pricing", html, "https://example.com/pricing", 200, 0.1)
        findings = evaluate_page_engagement(snap, is_root=False)
        cta_findings = [f for f in findings if "call-to-action" in f["title"].lower() or "cta" in f["title"].lower()]
        self.assertEqual(len(cta_findings), 0, "Page with submit button and form must not be flagged for missing CTA")

    def test_root_cause_deduplication_combines_evidence_and_picks_highest_severity(self):
        """Related findings sharing a root cause fingerprint must deduplicate cleanly."""
        f1 = {
            "title": "Missing canonical tag on /products",
            "category": "structured-data",
            "severity": "low",
            "evidence": "Observed missing canonical on /products",
            "source_skill": "crawl-render-audit",
            "fingerprint": "meta:missing-canonical",
            "suggested_action": {"summary": "Add canonical", "priority": "low", "how_to_fix": "Add link tag"}
        }
        f2 = {
            "title": "Missing canonical tag causing duplicate index risk",
            "category": "structured-data",
            "severity": "high",
            "evidence": "Observed canonical absent across multiple query params",
            "source_skill": "citation-simulator",
            "fingerprint": "meta:missing-canonical",
            "suggested_action": {"summary": "Add canonical tag", "priority": "high", "how_to_fix": "Add link tag"}
        }

        merged = dedupe([f1, f2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["severity"], "high")
        self.assertIn("crawl-render-audit", merged[0]["source_skills"])
        self.assertIn("citation-simulator", merged[0]["source_skills"])
        self.assertIn("Additional evidence", merged[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
