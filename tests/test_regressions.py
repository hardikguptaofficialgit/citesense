"""
test_regressions.py -- Locks in the fixes recorded in Progress.md (F1-F12).

Every test here corresponds to a bug that was live in the submission and produced a false
positive, a fabricated evidence string, or a guardrail violation on a real website. If one of
these fails, a regression has been reintroduced -- check Progress.md for the original repro.
"""
import gzip
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "engagement-audit", "freshness-corroboration",
            "citation-simulator", "trust-corroboration-graph", "audit-orchestrator"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from audit_common import decompress_body, decode_body, content_is_unreadable, header_get
from site_inventory import (
    SiteInventory, analyze_page_html, classify_page_purpose, FOUNDING_RE, COPYRIGHT_RE
)
from freshness_and_consistency_scan import evaluate_freshness_and_consistency
from generate_queries import evaluate_answerability
from corroboration_scorer import evaluate_identity_anchoring


class TransportRegressions(unittest.TestCase):
    """F1 -- gzip bodies were decoded as UTF-8 mojibake, faking 4 high findings on python.org."""

    def test_gzip_body_is_decompressed_by_header(self):
        html = "<html><head><title>Real Page</title></head><body><h1>Hi</h1></body></html>"
        raw = gzip.compress(html.encode())
        self.assertEqual(decode_body(decompress_body(raw, "gzip"), "text/html"), html)

    def test_gzip_body_is_decompressed_by_magic_bytes_when_header_absent(self):
        # python.org's CDN returns gzip even when the request did not advertise support
        html = "<html><head><title>Unsolicited gzip</title></head></html>"
        raw = gzip.compress(html.encode())
        self.assertIn("<title>", decode_body(decompress_body(raw, ""), "text/html"))

    def test_header_lookup_is_case_insensitive(self):
        # the live header arrives lowercase as 'content-encoding'
        self.assertEqual(header_get({"content-encoding": "gzip"}, "Content-Encoding"), "gzip")

    def test_undecoded_binary_is_flagged_unreadable(self):
        garbage = gzip.compress(b"x" * 4000).decode("utf-8", errors="replace")
        self.assertTrue(content_is_unreadable(garbage))
        self.assertFalse(content_is_unreadable("<html><body>Perfectly ordinary text.</body></html>"))


class InconclusivePageRegressions(unittest.TestCase):
    """F2 -- an unreadable page must yield no findings, not 'every tag is missing'."""

    def test_unreadable_page_snapshot_is_marked_inconclusive(self):
        garbage = gzip.compress(b"y" * 4000).decode("utf-8", errors="replace")
        snap = analyze_page_html("https://x.test/", garbage, "https://x.test/", 200, 0.1)
        self.assertTrue(snap["inconclusive"])

    def test_readable_page_is_not_inconclusive(self):
        html = "<html><head><title>Fine</title></head><body><h1>Fine</h1></body></html>"
        snap = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        self.assertFalse(snap["inconclusive"])


class FreshnessRegressions(unittest.TestCase):
    """F3 -- '(c) 2005-2026' was read as a stale 2005 notice on mozilla.org and django."""

    def test_copyright_range_resolves_to_the_newest_year(self):
        html = "<html><body><footer>&copy; 2005-2026 Example Foundation</footer></body></html>"
        snap = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        self.assertEqual(snap["dates_and_claims"]["newest_copyright_year"], 2026)

    def test_en_dash_copyright_range_resolves_to_the_newest_year(self):
        html = "<html><body><footer>Portions ©1998–2026 by contributors</footer></body></html>"
        snap = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        self.assertEqual(snap["dates_and_claims"]["newest_copyright_year"], 2026)

    def test_ranged_footer_produces_no_stale_copyright_finding(self):
        inv = SiteInventory("https://x.test")
        html = "<html><head><title>X</title></head><body><footer>&copy; 2005-2026 X</footer></body></html>"
        inv.pages["https://x.test/"] = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        stale = [f for f in evaluate_freshness_and_consistency(inv) if "copyright" in f["title"].lower()]
        self.assertEqual(stale, [])

    def test_stale_copyright_is_reported_once_for_the_whole_site(self):
        # F7 -- template-level defects previously fired once per crawled page (5x on mozilla.org)
        inv = SiteInventory("https://x.test")
        html = "<html><head><title>X</title></head><body><footer>&copy; 2011 X</footer></body></html>"
        for path in ("/", "/a", "/b", "/c"):
            u = "https://x.test" + path
            inv.pages[u] = analyze_page_html(u, html, u, 200, 0.1)
        stale = [f for f in evaluate_freshness_and_consistency(inv) if "copyright" in f["title"].lower()]
        self.assertEqual(len(stale), 1, "stale copyright must collapse into a single site-wide finding")


class FoundingClaimRegressions(unittest.TestCase):
    """F4 -- 'since 2019' in prose produced a HIGH 'contradictory founding year' on react.dev."""

    def test_bare_since_is_not_a_founding_claim(self):
        self.assertIsNone(FOUNDING_RE.search("This API has been supported since 2019."))
        self.assertIsNone(FOUNDING_RE.search("Deprecated since 2017 and removed later."))

    def test_explicit_founding_verbs_still_match(self):
        for text, year in [("Founded in 1998 in California", "1998"),
                           ("The company was established 2004", "2004"),
                           ("Incorporated in 2011", "2011")]:
            m = FOUNDING_RE.search(text)
            self.assertIsNotNone(m, text)
            self.assertEqual(m.group(1), year)

    def test_prose_since_years_produce_no_consistency_finding(self):
        inv = SiteInventory("https://x.test")
        for path, body in (("/blog", "Supported since 2019."), ("/team", "Available since 2017.")):
            u = "https://x.test" + path
            html = f"<html><head><title>X</title></head><body><p>{body}</p></body></html>"
            inv.pages[u] = analyze_page_html(u, html, u, 200, 0.1)
        mismatches = [f for f in evaluate_freshness_and_consistency(inv) if "founding" in f["title"].lower()]
        self.assertEqual(mismatches, [])


class PagePurposeRegressions(unittest.TestCase):
    """F5 -- substring matching made /restore a store and a blog post a money page."""

    def test_substrings_do_not_make_a_page_commercial(self):
        for url in ("https://x.test/restore", "https://x.test/workshop",
                    "https://x.test/buyers-guide", "https://x.test/frontier-guide"):
            self.assertNotEqual(classify_page_purpose(url, "", "", ""), "product_pricing", url)

    def test_dated_blog_permalink_is_editorial_not_commercial(self):
        url = "https://x.test/weblog/2025/apr/26/new-features-github-repo-and-project/"
        self.assertEqual(classify_page_purpose(url, "", "", ""), "article_docs")

    def test_genuine_pricing_page_still_classifies_as_commercial(self):
        self.assertEqual(classify_page_purpose("https://x.test/pricing", "Pricing", "Plans", ""), "product_pricing")
        self.assertEqual(classify_page_purpose("https://x.test/shop", "Shop", "", ""), "product_pricing")


class RobotsEnforcementRegressions(unittest.TestCase):
    """F6 -- robots.txt was parsed but never gated our own fetches."""

    def _inv(self):
        inv = SiteInventory("https://x.test")
        inv.robots_txt = {"found": True, "raw": "User-agent: *\nDisallow: /private\n"}
        from audit_common import parse_robots
        inv._robots_groups = parse_robots(inv.robots_txt["raw"])
        return inv

    def test_disallowed_path_is_refused(self):
        inv = self._inv()
        self.assertFalse(inv.may_fetch("https://x.test/private/data"))
        self.assertTrue(any(s["url"].endswith("/private/data") for s in inv.skipped_by_robots))

    def test_allowed_path_is_permitted(self):
        self.assertTrue(self._inv().may_fetch("https://x.test/about"))

    def test_offsite_url_is_never_crawled(self):
        self.assertFalse(self._inv().may_fetch("https://other.test/anything"))

    def test_robots_state_survives_inventory_roundtrip(self):
        restored = SiteInventory.from_dict(self._inv().to_dict())
        self.assertFalse(restored.may_fetch("https://x.test/private/x"))


class EvidenceHonestyRegressions(unittest.TestCase):
    """F8/F9/F10 -- no check may describe an observation it did not make."""

    def test_identity_anchoring_stays_silent_when_an_authority_link_exists(self):
        out = evaluate_identity_anchoring("X", "https://x.test", [], ["github.com"], True)
        self.assertEqual(out, [])

    def test_identity_anchoring_fires_with_observation_based_evidence_only(self):
        out = evaluate_identity_anchoring("X", "https://x.test", [], ["cdn.example.test"], True)
        self.assertEqual(len(out), 1)
        evidence = out[0]["evidence"]
        self.assertNotIn("Searched external sources", evidence)
        self.assertIn("outbound link domains", evidence)

    def test_sameas_to_authority_counts_as_anchored(self):
        out = evaluate_identity_anchoring("X", "https://x.test", ["https://www.wikidata.org/wiki/Q1"], [], True)
        self.assertEqual(out, [])

    def test_pricing_probe_does_not_fire_on_a_non_commercial_site(self):
        inv = {"pages": {"u": {
            "inconclusive": False, "status_code": 200, "page_purpose": "article_docs",
            "visible_text": "A documentation site about a library.", "jsonld_parsed": [],
        }}}
        titles = [f["title"] for f in evaluate_answerability(inv, {"brand_name": "Lib"}, "x.test")]
        self.assertFalse(any("cost" in t for t in titles), "must not manufacture a pricing gap on a docs site")

    def test_answerability_is_silent_when_the_facts_are_present(self):
        inv = {"pages": {"u": {
            "inconclusive": False, "status_code": 200, "page_purpose": "product_pricing",
            "visible_text": "Plans from $10 per month. Email sales@x.test to get started.",
            "jsonld_parsed": [{"@type": "Organization", "name": "X"}, {"@type": "Product", "name": "P"}],
        }}}
        self.assertEqual(evaluate_answerability(inv, {"brand_name": "X"}, "x.test"), [])

    def test_inconclusive_pages_cannot_drive_answerability_findings(self):
        inv = {"pages": {"u": {"inconclusive": True, "status_code": 200}}}
        self.assertEqual(evaluate_answerability(inv, {"brand_name": "X"}, "x.test"), [])


class BrandNameRegressions(unittest.TestCase):
    """F12 -- the page tagline leaked into queries as the brand name."""

    def test_tagline_title_does_not_become_the_brand_name(self):
        inv = SiteInventory("https://www.acme.test")
        html = "<html><head><title>Software for people, not profit - Acme</title></head><body>x</body></html>"
        snap = analyze_page_html("https://www.acme.test/", html, "https://www.acme.test/", 200, 0.1)
        inv.pages["https://www.acme.test/"] = snap
        inv._extract_ground_truth(snap)
        self.assertNotIn("not profit", inv.ground_truth["brand_name"])

    def test_og_site_name_wins_over_title(self):
        inv = SiteInventory("https://x.test")
        html = ('<html><head><title>Welcome to the best widgets on earth</title>'
                '<meta property="og:site_name" content="Acme"></head><body>x</body></html>')
        snap = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        inv.pages["https://x.test/"] = snap
        inv._extract_ground_truth(snap)
        self.assertEqual(inv.ground_truth["brand_name"], "Acme")

    def test_organization_schema_name_wins_over_everything(self):
        inv = SiteInventory("https://x.test")
        html = ('<html><head><title>Some tagline here</title>'
                '<meta property="og:site_name" content="Wrong">'
                '<script type="application/ld+json">{"@type":"Organization","name":"Acme Inc","url":"https://x.test"}</script>'
                '</head><body>x</body></html>')
        snap = analyze_page_html("https://x.test/", html, "https://x.test/", 200, 0.1)
        inv.pages["https://x.test/"] = snap
        inv._extract_ground_truth(snap)
        self.assertEqual(inv.ground_truth["brand_name"], "Acme Inc")


if __name__ == "__main__":
    unittest.main()


class ContractDriftTests(unittest.TestCase):
    """
    Guards against the two contracts silently diverging. models.py, compose_report.py and
    report-schema.json each encode the category vocabulary; when they drift, the
    discoverability/engagement split in the summary is silently wrong.
    """

    def _schema(self):
        import json
        return json.loads((ROOT / "skills/audit-orchestrator/references/report-schema.json").read_text(encoding="utf-8"))

    def test_schema_enum_matches_models_categories(self):
        from models import VALID_CATEGORIES
        enum = set(self._schema()["properties"]["findings"]["items"]["properties"]["category"]["enum"])
        self.assertEqual(enum, VALID_CATEGORIES)

    def test_every_category_is_classified_as_discoverability_or_engagement(self):
        from models import VALID_CATEGORIES, DISCOVERABILITY_CATEGORIES, ENGAGEMENT_CATEGORIES
        unclassified = VALID_CATEGORIES - (DISCOVERABILITY_CATEGORIES | ENGAGEMENT_CATEGORIES)
        self.assertEqual(unclassified, set(), "these categories would be dropped from the summary split")
        self.assertEqual(DISCOVERABILITY_CATEGORIES & ENGAGEMENT_CATEGORIES, set())

    def test_compose_report_uses_the_same_sets_as_models(self):
        import models, compose_report
        self.assertIs(compose_report.DISCOVERABILITY_CATEGORIES, models.DISCOVERABILITY_CATEGORIES)
        self.assertIs(compose_report.ENGAGEMENT_CATEGORIES, models.ENGAGEMENT_CATEGORIES)

    def test_schema_requires_what_the_validator_enforces(self):
        # assign_ids_and_validate() rejects a finding without how_to_fix, so the schema must say so
        required = self._schema()["properties"]["findings"]["items"]["properties"]["suggested_action"]["required"]
        self.assertIn("how_to_fix", required)


class InventoryDeduplicationTests(unittest.TestCase):
    """A redirected page was stored under both its requested and final URL, so a 5-page crawl
    reported 6 pages and every 'across N crawled pages' evidence string overcounted."""

    def test_redirected_page_is_stored_once_under_its_final_url(self):
        inv = SiteInventory("https://x.test")
        snap = analyze_page_html(
            "https://x.test/psf-landing/",
            "<html><head><title>T</title></head><body><h1>H</h1></body></html>",
            "https://x.test/psf/", 200, 0.1,
        )
        inv.store_page("https://x.test/psf-landing/", snap)
        self.assertEqual(len(inv.pages), 1)
        self.assertIn("https://x.test/psf/", inv.pages)
        self.assertEqual(inv.url_aliases["https://x.test/psf-landing/"], "https://x.test/psf/")

    def test_knows_url_recognises_both_sides_of_a_redirect(self):
        inv = SiteInventory("https://x.test")
        snap = analyze_page_html(
            "https://x.test/a", "<html><head><title>T</title></head><body>b</body></html>",
            "https://x.test/b", 200, 0.1,
        )
        inv.store_page("https://x.test/a", snap)
        self.assertTrue(inv.knows_url("https://x.test/a"))
        self.assertTrue(inv.knows_url("https://x.test/b"))
        self.assertFalse(inv.knows_url("https://x.test/c"))

    def test_aliases_survive_an_inventory_roundtrip(self):
        inv = SiteInventory("https://x.test")
        inv.url_aliases = {"https://x.test/a": "https://x.test/b"}
        self.assertTrue(SiteInventory.from_dict(inv.to_dict()).knows_url("https://x.test/a"))


class ScoreHonestyRegressions(unittest.TestCase):
    """
    A score computed from an unreadable crawl is the F2 failure class at the scoring layer:
    penalties subtract from 100 per finding, so a site that returned 404 produces almost no
    findings and scores near-perfect. kforum.me scored 90/100 while serving HTTP 404.
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

    def _report(self):
        return {
            "site": "https://x.test",
            "summary": {"total_findings": 1, "critical": 0, "high": 0, "medium": 1, "low": 0},
            "findings": [{
                "id": "F-001", "title": "t", "severity": "medium", "category": "crawlability",
                "evidence": "observed something concrete here",
                "suggested_action": {"summary": "s", "priority": "medium", "how_to_fix": "h"},
            }],
        }

    def test_score_is_withheld_when_no_page_could_be_read(self):
        from scored import annotate_report
        pages = {"https://x.test/": {"status_code": 404, "inconclusive": True}}
        summary = annotate_report(self._report(), pages=pages)["summary"]
        self.assertNotIn("citability_score", summary)
        self.assertIn("citability_score_unavailable", summary)

    def test_score_is_computed_when_at_least_one_page_was_read(self):
        from scored import annotate_report
        pages = {
            "https://x.test/": {"status_code": 200, "inconclusive": False},
            "https://x.test/a": {"status_code": 404, "inconclusive": True},
        }
        summary = annotate_report(self._report(), pages=pages)["summary"]
        self.assertIsInstance(summary.get("citability_score"), int)
        self.assertNotIn("citability_score_unavailable", summary)

    def test_undecodable_page_also_withholds_the_score(self):
        from scored import annotate_report
        pages = {"https://x.test/": {"status_code": 200, "inconclusive": True}}
        self.assertNotIn("citability_score", annotate_report(self._report(), pages=pages)["summary"])

    def test_callers_that_pass_no_pages_still_get_a_score(self):
        from scored import annotate_report
        self.assertIsInstance(annotate_report(self._report())["summary"].get("citability_score"), int)

    def test_end_to_end_404_site_yields_no_score(self):
        from compose_report import build_final_report
        report = build_final_report(
            site_url="https://x.test",
            findings=[],
            pages={"https://x.test/": {"status_code": 404, "inconclusive": True}},
        )
        self.assertNotIn("citability_score", report["summary"])
        self.assertIn("citability_score_unavailable", report["summary"])
