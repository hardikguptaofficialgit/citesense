import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "audit-orchestrator", "citation-simulator", "freshness-corroboration"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from compose_report import build_final_report
from freshness_and_consistency_scan import evaluate_freshness_and_consistency
from generate_queries import evaluate_answerability
from models import create_candidate_finding
from render_and_data_scan import evaluate_page_render_and_data, schema
from site_inventory import SiteInventory, analyze_page_html, classify_page_purpose
from run_audit import _prepare_external_evidence


class PersonaFixtureTests(unittest.TestCase):
    def test_persona_routes_cover_saas_ecommerce_local_university_docs_and_news(self):
        cases = [
            ("https://site.test/pricing", "SaaS plans", "Plans", "product_pricing"),
            ("https://site.test/products/widget", "Widget", "Widget", "product_pricing"),
            ("https://site.test/about", "Local business", "Our business", "contact_support"),
            ("https://site.test/admissions", "University admissions", "Admissions", "general"),
            ("https://site.test/docs/api", "API documentation", "API", "article_docs"),
            ("https://site.test/news/2026/launch", "News", "Launch", "article_docs"),
        ]
        for url, title, h1, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(classify_page_purpose(url, title, h1, ""), expected)

    def test_local_business_university_and_news_schema_are_parsed(self):
        html = """<html><head><title>City Clinic</title></head><body>
        <h1>City Clinic</h1><p>Care for families in Pune.</p>
        <script type="application/ld+json">{"@type":"LocalBusiness","name":"City Clinic","address":{"streetAddress":"1 Main St"}}</script>
        <script type="application/ld+json">{"@type":"CollegeOrUniversity","name":"Pune University"}</script>
        <script type="application/ld+json">{"@type":"NewsArticle","headline":"A story","datePublished":"2026-01-01"}</script>
        </body></html>"""
        parsed = schema(html, "https://site.test/", "City Clinic")
        self.assertEqual(parsed["jsonld_parse_errors"], [])
        self.assertEqual(parsed["entities"], 3)
        self.assertTrue(all(not item["missing_important_fields"] for item in parsed["validation"]))

    def test_missing_and_wrong_structured_data_produce_evidence(self):
        snap = analyze_page_html(
            "https://site.test/pricing",
            "<html><head><title>Pricing</title></head><body><h1>Plans</h1><p>From $10/month.</p></body></html>",
            "https://site.test/pricing",
            200,
            0.1,
        )
        findings = evaluate_page_render_and_data(snap)
        self.assertTrue(any(f["category"] == "structured-data" for f in findings))
        self.assertTrue(all(f["evidence_details"]["evidence_id"].startswith("E-") for f in findings))

    def test_duplicate_jsonld_ids_are_exposed_for_review(self):
        html = """<script type="application/ld+json">{"@id":"https://site.test/#org","@type":"Organization","name":"Acme","url":"https://site.test"}</script>
        <script type="application/ld+json">{"@id":"https://site.test/#org","@type":"Organization","name":"Acme","url":"https://site.test"}</script>"""
        self.assertEqual(schema(html, "https://site.test/", "Acme")["duplicate_entity_ids"], ["https://site.test/#org"])


class QualityRegressionFixtureTests(unittest.TestCase):
    def test_spa_shell_has_static_signals_but_complete_page_does_not(self):
        shell = analyze_page_html(
            "https://site.test/",
            '<html><body><div id="root"></div>' + ("<script>x</script>" * 20) + "</body></html>",
            "https://site.test/",
            200,
            0.1,
        )
        complete = analyze_page_html(
            "https://site.test/",
            "<html><body><h1>Acme</h1><p>Cloud software for teams.</p><script src=\"app.js\"></script></body></html>",
            "https://site.test/",
            200,
            0.1,
        )
        self.assertTrue(shell["render_gap"])
        self.assertTrue(shell["render_diff"]["signals"])
        self.assertFalse(complete["render_gap"])

    def test_stale_and_conflicting_facts_are_separate_evidence_backed_findings(self):
        inv = SiteInventory("https://site.test")
        for path, body in (
            ("/", "Acme was founded in 2012. Contact 555-111-2222. Promotion sale in 2020."),
            ("/about", "Acme was founded in 2018. Contact 555-333-4444."),
        ):
            url = "https://site.test" + path
            inv.pages[url] = analyze_page_html(
                url,
                f"<html><head><title>Acme</title></head><body><h1>Acme</h1><p>{body}</p></body></html>",
                url,
                200,
                0.1,
            )
        findings = evaluate_freshness_and_consistency(inv)
        titles = [f["title"] for f in findings]
        self.assertTrue(any("founding year" in title for title in titles))
        self.assertTrue(any("phone" in title.lower() for title in titles))
        self.assertTrue(any("time-sensitive" in title for title in titles))

    def test_evidence_ledger_and_assessments_are_machine_readable(self):
        finding = create_candidate_finding(
            title="Missing identity schema",
            category="structured-data",
            severity="medium",
            url="https://site.test/",
            observation="Homepage contains no Organization JSON-LD.",
            method="fixture",
            source_skill="test",
            action_summary="Add identity schema.",
            action_priority="medium",
            action_how_to_fix="Add Organization JSON-LD with observed brand data.",
        ).to_dict()
        report = build_final_report(
            "https://site.test",
            [finding],
            assessments=[{
                "check": "page_access",
                "status": "confirmed",
                "result": "passed",
                "reason": "Synthetic page was readable.",
            }],
        )
        self.assertEqual(len(report["evidence_ledger"]), 1)
        self.assertEqual(report["findings"][0]["evidence_refs"], [report["evidence_ledger"][0]["evidence_id"]])
        self.assertEqual(report["assessments"][0]["status"], "confirmed")
        self.assertIn("expected_benefit", report["findings"][0]["suggested_action"])

    def test_semantic_page_selection_prefers_information_routes(self):
        inv = SiteInventory("https://site.test")
        inv._robots_groups = []
        inv.pages["https://site.test/"] = analyze_page_html(
            "https://site.test/",
            """<html><body><a href="/random">Read more</a><a href="/platform">Platform</a>
            <a href="/customers">Customers</a><a href="/docs/api">API docs</a></body></html>""",
            "https://site.test/",
            200,
            0.1,
        )
        # Exercise the scoring contract directly without making network calls.
        candidates = inv.pages["https://site.test/"]["internal_links"]
        self.assertEqual([c["text"] for c in candidates[:2]], ["Read more", "Platform"])
        self.assertTrue(any("docs" in c["href"] for c in candidates))

    def test_answerability_is_evidence_scoped(self):
        inventory = {
            "pages": {
                "https://site.test/": {
                    "inconclusive": False,
                    "status_code": 200,
                    "page_purpose": "homepage",
                    "title": "Acme",
                    "visible_text": "Acme is a university for engineers.",
                    "jsonld_parsed": [{"@type": "Organization", "name": "Acme"}],
                },
                "https://site.test/pricing": {
                    "inconclusive": False,
                    "status_code": 200,
                    "page_purpose": "product_pricing",
                    "title": "Plans",
                    "visible_text": "Plans start at $10 per month for teams.",
                    "jsonld_parsed": [],
                },
            }
        }
        findings = evaluate_answerability(inventory, {"brand_name": "Acme"}, "site.test")
        self.assertFalse(any("cost" in f["title"].lower() for f in findings))

    def test_agent_supplied_external_evidence_is_indexed_without_network_lookup(self):
        citations, trust, records = _prepare_external_evidence({
            "citation_simulation": [{
                "query": "What is Acme?",
                "classification": "omission",
                "surfaced_urls": ["https://search.example/result"],
                "evidence": "Agent observed that the official domain was absent from supplied results.",
            }],
            "trust": {
                "facts": [{
                    "fact": "Acme was founded in 2012",
                    "sources": [{
                        "domain": "registry.example",
                        "url": "https://registry.example/acme",
                        "supports_fact": True,
                        "evidence": "Registry record lists Acme as founded in 2012.",
                    }],
                }]
            },
        })
        self.assertEqual(len(citations), 1)
        self.assertEqual(len(trust["facts"]), 1)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["evidence_origin"] == "external" for record in records))
        self.assertTrue(all(record["evidence_id"].startswith("E-") for record in records))

        report = build_final_report(
            "https://site.test",
            [],
            assessments=[{
                "check": "off_site_discovery",
                "status": "confirmed",
                "result": "assessed",
                "reason": "Caller supplied evidence.",
                "evidence_refs": [record["evidence_id"] for record in records],
            }],
            external_evidence=records,
        )
        self.assertEqual(report["external_discovery"]["network_lookup_performed"], False)
        self.assertEqual(
            set(report["external_discovery"]["evidence_refs"]),
            {record["evidence_id"] for record in report["evidence_ledger"]},
        )


if __name__ == "__main__":
    unittest.main()
