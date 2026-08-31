"""
test_origin_and_shell.py -- Bugs found by auditing small real-world sites rather than
well-built engineering sites.

The validation set was six technically strong sites, all seeded with their final hostname.
That hid a regression that reduced any apex-redirects-to-www site to a one-page crawl, and a
render-gap threshold that missed genuinely empty single-page-app shells.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "engagement-audit"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from site_inventory import SiteInventory, analyze_page_html
from render_and_data_scan import evaluate_page_render_and_data
from engagement_scan import evaluate_page_engagement

SHELL = '<html><head><title>App</title></head><body><div id="root"></div>' + ("<script>x</script>" * 120) + "</body></html>"
SHORT_BUT_COMPLETE = (
    "<html><head><title>Acme Widgets</title></head><body><h1>Acme Widgets</h1>"
    "<p>Enterprise cloud security from $49/month. Contact support@acme.test.</p>"
    '<script src="/app.bundle.js"></script></body></html>'
)


class OriginRedirectTests(unittest.TestCase):
    """An apex host redirecting to www left origin on the apex while every page lived on www,
    so the same-site gate refused every internal link and the crawl stopped at one page."""

    def test_apex_and_www_are_the_same_site(self):
        inv = SiteInventory("https://acme.test")
        self.assertTrue(inv.same_site("https://www.acme.test/x"))
        self.assertTrue(inv.same_site("https://acme.test/x"))
        self.assertFalse(inv.same_site("https://other.test/x"))

    def test_www_links_are_fetchable_when_seeded_with_the_apex(self):
        inv = SiteInventory("https://acme.test")
        self.assertTrue(inv.may_fetch("https://www.acme.test/events"))

    def test_apex_links_are_fetchable_when_seeded_with_www(self):
        inv = SiteInventory("https://www.acme.test")
        self.assertTrue(inv.may_fetch("https://acme.test/events"))

    def test_offsite_is_still_refused(self):
        inv = SiteInventory("https://acme.test")
        self.assertFalse(inv.may_fetch("https://evil.test/x"))

    def test_robots_still_enforced_across_the_www_boundary(self):
        from audit_common import parse_robots
        inv = SiteInventory("https://acme.test")
        inv._robots_groups = parse_robots("User-agent: *\nDisallow: /private\n")
        self.assertFalse(inv.may_fetch("https://www.acme.test/private/x"))
        self.assertTrue(inv.may_fetch("https://www.acme.test/public"))


class ShellPageTests(unittest.TestCase):
    """A client-rendered shell is one root cause, not eleven findings."""

    def test_empty_shell_is_flagged_as_a_render_gap(self):
        snap = analyze_page_html("https://acme.test/", SHELL, "https://acme.test/", 200, 0.1)
        self.assertTrue(snap["render_gap"])

    def test_short_but_complete_page_is_not_a_render_gap(self):
        snap = analyze_page_html("https://acme.test/", SHORT_BUT_COMPLETE, "https://acme.test/", 200, 0.1)
        self.assertFalse(snap["render_gap"], "a brief page carrying its heading and facts is complete, not a shell")

    def test_shell_yields_exactly_one_finding_not_a_cascade(self):
        snap = analyze_page_html("https://acme.test/", SHELL, "https://acme.test/", 200, 0.1)
        findings = evaluate_page_render_and_data(snap, is_root=True)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "render-gap")

    def test_engagement_stays_silent_on_a_shell(self):
        snap = analyze_page_html("https://acme.test/", SHELL, "https://acme.test/", 200, 0.1)
        self.assertEqual(evaluate_page_engagement(snap, is_root=True), [])

    def test_render_gap_evidence_says_other_checks_were_suppressed(self):
        snap = analyze_page_html("https://acme.test/", SHELL, "https://acme.test/", 200, 0.1)
        ev = evaluate_page_render_and_data(snap, is_root=True)[0]["evidence"]
        self.assertIn("suppressed", ev.lower())

    def test_a_normal_page_still_gets_its_page_level_findings(self):
        html = '<html><head><title>T</title></head><body><p>' + ("word " * 200) + "</p></body></html>"
        snap = analyze_page_html("https://acme.test/", html, "https://acme.test/", 200, 0.1)
        self.assertFalse(snap["render_gap"])
        self.assertTrue(evaluate_page_engagement(snap, is_root=True), "missing h1 should still be reported")


if __name__ == "__main__":
    unittest.main()
