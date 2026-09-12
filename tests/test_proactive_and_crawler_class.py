"""
test_proactive_and_crawler_class.py -- Cover for the September 2026 standards work.

Two things are locked in here:
  1. AI crawlers are scored by consequence class. Blocking training crawlers is a legitimate
     licensing choice and must not be reported as a citation defect.
  2. Proactive recommendations fire on observed conditions and are never empty for a site with
     obvious headroom -- that rubric criterion previously scored zero on 2 of 6 validation sites.

Evidence basis: skills/audit-orchestrator/references/ai-visibility-standards-2026.md
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "audit-orchestrator"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from audit_common import (
    AI_CRAWLER_CLASSES, AI_USER_AGENTS, CITATION_CRITICAL_AGENTS,
    crawler_class, parse_robots, robot_decision,
)
from site_inventory import SiteInventory, analyze_page_html
from crawlability_check import evaluate_crawlability
from proactive_recommendations import generate_proactive_recommendations, MAX_RECOMMENDATIONS


def build_inventory(robots_raw, pages=None):
    inv = SiteInventory("https://acme.test")
    inv.origin = "https://acme.test"
    groups = parse_robots(robots_raw)
    test_paths = ["/", "/pricing", "/about"]
    decisions = {a: {p: robot_decision(groups, a, p) for p in test_paths} for a in AI_USER_AGENTS}
    inv.robots_txt = {
        "found": True, "url": "https://acme.test/robots.txt", "status": 200, "raw": robots_raw,
        "agent_decisions": decisions,
        "partially_blocked_agents": {},
        "sitemaps_declared": ["https://acme.test/sitemap.xml"],
    }
    inv.sitemaps = [{"url": "https://acme.test/sitemap.xml", "found": True,
                     "status": 200, "discovered_url_count": 3}]
    for u, snap in (pages or []):
        inv.pages[u] = snap
    return inv


def make_page(url, body):
    html = f"<html><head><title>T</title></head><body>{body}</body></html>"
    return analyze_page_html(url, html, url, 200, 0.1)


class CrawlerClassTests(unittest.TestCase):
    """Blocking a training crawler costs no citations; blocking a retrieval agent costs all of them."""

    def test_classes_are_disjoint_and_citation_set_is_derived(self):
        seen = [a for g in AI_CRAWLER_CLASSES.values() for a in g]
        self.assertEqual(len(seen), len(set(seen)), "an agent appears in two classes")
        self.assertEqual(
            set(CITATION_CRITICAL_AGENTS),
            set(AI_CRAWLER_CLASSES["search_index"]) | set(AI_CRAWLER_CLASSES["user_triggered"]),
        )

    def test_current_anthropic_agents_are_present_and_classified(self):
        self.assertEqual(crawler_class("Claude-SearchBot"), "search_index")
        self.assertEqual(crawler_class("Claude-User"), "user_triggered")
        self.assertEqual(crawler_class("ClaudeBot"), "training")

    def test_blocking_training_crawlers_only_is_not_a_citation_defect(self):
        robots = "User-agent: GPTBot\nDisallow: /\nUser-agent: ClaudeBot\nDisallow: /\nUser-agent: *\nDisallow:\n"
        findings = evaluate_crawlability(build_inventory(robots))
        blocked = [f for f in findings if f["category"] == "crawlability" and "blocked" in f["title"].lower()]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["severity"], "low")
        self.assertEqual(blocked[0]["status"], "proactive")

    def test_blocking_a_search_index_crawler_is_critical(self):
        robots = "User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: *\nDisallow:\n"
        crit = [f for f in evaluate_crawlability(build_inventory(robots)) if f["severity"] == "critical"]
        self.assertEqual(len(crit), 1)
        self.assertIn("OAI-SearchBot", crit[0]["evidence"])

    def test_blocking_a_user_triggered_fetcher_is_critical(self):
        robots = "User-agent: Perplexity-User\nDisallow: /\nUser-agent: *\nDisallow:\n"
        crit = [f for f in evaluate_crawlability(build_inventory(robots)) if f["severity"] == "critical"]
        self.assertEqual(len(crit), 1)

    def test_mixed_block_is_critical_and_names_the_training_stance_separately(self):
        robots = ("User-agent: GPTBot\nDisallow: /\nUser-agent: OAI-SearchBot\nDisallow: /\n"
                  "User-agent: *\nDisallow:\n")
        crit = [f for f in evaluate_crawlability(build_inventory(robots)) if f["severity"] == "critical"]
        self.assertEqual(len(crit), 1)
        self.assertIn("licensing choice", crit[0]["evidence"])

    def test_fully_open_robots_produces_no_blocking_finding(self):
        findings = evaluate_crawlability(build_inventory("User-agent: *\nDisallow:\n"))
        self.assertEqual([f for f in findings if "blocked" in f["title"].lower()], [])


class ProactiveRecommendationTests(unittest.TestCase):
    """This rubric criterion previously scored zero on react.dev and stripe.com."""

    def test_a_bare_site_receives_substantive_recommendations(self):
        inv = build_inventory("User-agent: *\nDisallow:\n", [
            ("https://acme.test/", make_page("https://acme.test/", "<h1>Acme</h1><p>We sell things.</p>"))])
        recs = generate_proactive_recommendations(inv)
        self.assertGreaterEqual(len(recs), 1)
        for r in recs:
            self.assertTrue(r["title"] and r["rationale"])
            self.assertIn(r["suggested_action"]["priority"], {"high", "medium", "low"})
            self.assertTrue(r["suggested_action"]["how_to_fix"])

    def test_faq_recommendation_fires_only_when_question_content_exists(self):
        with_q = build_inventory("User-agent: *\nDisallow:\n", [(
            "https://acme.test/",
            make_page("https://acme.test/", "<h1>Acme</h1><h2>How do I reset my password?</h2><p>Click reset.</p>"))])
        self.assertTrue(any("FAQPage" in r["title"] for r in generate_proactive_recommendations(with_q)))

        without_q = build_inventory("User-agent: *\nDisallow:\n", [(
            "https://acme.test/",
            make_page("https://acme.test/", "<h1>Acme</h1><h2>Our team</h2><p>We are here.</p>"))])
        self.assertFalse(any("FAQPage" in r["title"] for r in generate_proactive_recommendations(without_q)))

    def test_third_party_anchoring_suppressed_when_authority_links_exist(self):
        body = ('<h1>Acme</h1><a href="https://www.wikidata.org/wiki/Q1">wikidata</a>'
                '<a href="https://github.com/acme">gh</a>')
        inv = build_inventory("User-agent: *\nDisallow:\n",
                              [("https://acme.test/", make_page("https://acme.test/", body))])
        self.assertFalse(any("third-party presence" in r["title"]
                             for r in generate_proactive_recommendations(inv)))

    def test_llms_txt_is_low_priority_and_discloses_the_weak_evidence(self):
        inv = build_inventory("User-agent: *\nDisallow:\n",
                              [("https://acme.test/", make_page("https://acme.test/", "<h1>Acme</h1>"))])
        inv.special_files = {"llms_txt": {"found": False}}
        rec = [r for r in generate_proactive_recommendations(inv) if "llms.txt" in r["title"]]
        if rec:
            self.assertEqual(rec[0]["suggested_action"]["priority"], "low")
            self.assertIn("no effect", rec[0]["rationale"].lower())

    def test_recommendations_lead_with_the_strongest_evidence_and_are_capped(self):
        body = "<h1>Acme</h1><h2>What is Acme?</h2><p>A thing.</p>" + ("<p>Filler sentence here. </p>" * 40)
        inv = build_inventory("User-agent: *\nDisallow:\n",
                              [("https://acme.test/docs/a", make_page("https://acme.test/docs/a", body))])
        recs = generate_proactive_recommendations(inv)
        self.assertLessEqual(len(recs), MAX_RECOMMENDATIONS)
        rank = {"high": 0, "medium": 1, "low": 2}
        priorities = [rank[r["suggested_action"]["priority"]] for r in recs]
        self.assertEqual(priorities, sorted(priorities))

    def test_no_recommendations_from_an_inconclusive_crawl(self):
        inv = build_inventory("User-agent: *\nDisallow:\n")
        inv.pages["https://acme.test/"] = {"inconclusive": True, "status_code": 200}
        self.assertEqual(generate_proactive_recommendations(inv), [])

    def test_every_recommendation_matches_the_report_schema(self):
        import json
        schema = json.loads((ROOT / "skills/audit-orchestrator/references/report-schema.json").read_text(encoding="utf-8"))
        required = set(schema["properties"]["proactive_recommendations"]["items"]["required"])
        inv = build_inventory("User-agent: *\nDisallow:\n", [(
            "https://acme.test/",
            make_page("https://acme.test/", "<h1>Acme</h1><h2>What is this?</h2><p>A thing.</p>"))])
        for r in generate_proactive_recommendations(inv):
            self.assertTrue(required <= set(r.keys()), f"missing {required - set(r.keys())}")


if __name__ == "__main__":
    unittest.main()
