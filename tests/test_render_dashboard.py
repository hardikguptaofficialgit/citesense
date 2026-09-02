"""
test_render_dashboard.py -- Tests the self-contained HTML dashboard renderer.

Asserts the output is well-formed HTML (parsed, not string-matched), carries the site name
and every finding title, stays free of external requests, and degrades gracefully when the
optional proactive_recommendations block is absent.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from render_dashboard import render_dashboard

SCRIPT = ROOT / "skills/audit-orchestrator/scripts/render_dashboard.py"

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

MINIMAL_REPORT = {
    "site": "https://acme.test",
    "audited_at": "2026-01-01T00:00:00Z",
    "summary": {
        "total_findings": 2,
        "critical": 1,
        "high": 0,
        "medium": 1,
        "low": 0,
        "discoverability_findings": 1,
        "engagement_findings": 1,
        "citability_score": 70,
    },
    "findings": [
        {
            "id": "F-001",
            "title": "AI assistant crawler is disallowed in robots.txt",
            "category": "crawlability",
            "severity": "critical",
            "status": "confirmed",
            "confidence": "high",
            "evidence": "Observed at https://acme.test/robots.txt via robots_parser "
                        "[2026-01-01T00:00:00Z]: GPTBot is disallowed for / while * is open. "
                        "This is a long evidence string used to exercise the collapsible "
                        "disclosure path in the renderer, well past the collapse threshold "
                        "so that the details element is emitted instead of an inline block.",
            "source_skill": "crawl-render-audit",
            "fingerprint": "crawl:ai-agent-disallowed",
            "suggested_action": {
                "summary": "Allow AI assistant crawlers.",
                "priority": "critical",
                "how_to_fix": "Remove the Disallow: / rule for GPTBot in robots.txt.",
            },
        },
        {
            "id": "F-002",
            "title": "Primary navigation has no visible orientation cues",
            "category": "orientation",
            "severity": "medium",
            "status": "likely-risk",
            "confidence": "medium",
            "evidence": "Observed at https://acme.test/ via dom_inspector: no landmark nav.",
            "source_skill": "engagement-audit",
            "fingerprint": "engagement:no-orientation",
            "suggested_action": {
                "summary": "Add orientation cues.",
                "priority": "medium",
                "how_to_fix": "Add a labelled <nav> landmark with a current-page indicator.",
                "fix_snippet": '<script type="application/ld+json">\n{"@type": "X"}\n</script>',
            },
        },
    ],
    "proactive_recommendations": [
        {
            "title": "Publish an llms.txt manifest",
            "rationale": "Gives assistants a curated map of authoritative documentation.",
            "suggested_action": {
                "summary": "Create /llms.txt.",
                "priority": "low",
                "how_to_fix": "Add markdown links to the core product and docs pages.",
            },
        }
    ],
}


class WellFormednessChecker(HTMLParser):
    """Verifies tags nest and close correctly, and records src/href hosts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.external_refs = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("src", "href") and value and "://" in value:
                self.external_refs.append(value)
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)
        if tag == "title":
            self._in_title = True

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append("closing </%s> with empty stack" % tag)
        elif self.stack[-1] != tag:
            self.errors.append("closing </%s> while inside <%s>" % (tag, self.stack[-1]))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(document):
    checker = WellFormednessChecker()
    checker.feed(document)
    checker.close()
    return checker


class RenderDashboardTests(unittest.TestCase):

    def test_output_is_well_formed_html(self):
        checker = parse(render_dashboard(MINIMAL_REPORT))
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [], "unclosed tags: %s" % checker.stack)

    def test_contains_site_name_and_timestamp(self):
        document = render_dashboard(MINIMAL_REPORT)
        self.assertIn("https://acme.test", document)
        self.assertIn("2026-01-01T00:00:00Z", document)
        self.assertIn("acme.test", parse(document).title)

    def test_contains_every_finding_title(self):
        document = render_dashboard(MINIMAL_REPORT)
        for f in MINIMAL_REPORT["findings"]:
            self.assertIn(f["title"], document)

    def test_renders_severity_summary_and_split(self):
        document = render_dashboard(MINIMAL_REPORT)
        self.assertIn("Critical", document)
        self.assertIn("Discoverability", document)
        self.assertIn("On-site engagement", document)

    def test_shows_citability_score_when_present(self):
        self.assertIn("AI-Citability Score", render_dashboard(MINIMAL_REPORT))

    def test_omits_citability_score_when_absent(self):
        report = json.loads(json.dumps(MINIMAL_REPORT))
        del report["summary"]["citability_score"]
        self.assertNotIn("AI-Citability Score", render_dashboard(report))

    def test_long_evidence_is_collapsible(self):
        self.assertIn("<details", render_dashboard(MINIMAL_REPORT))

    def test_fix_snippet_is_rendered_and_escaped(self):
        document = render_dashboard(MINIMAL_REPORT)
        self.assertIn("Ready-to-paste JSON-LD snippet", document)
        # The snippet must appear as escaped text, never as a live script tag.
        self.assertIn("&lt;script type=&quot;application/ld+json&quot;&gt;", document)

    def test_proactive_section_present_and_distinct(self):
        document = render_dashboard(MINIMAL_REPORT)
        self.assertIn("Proactive Recommendations", document)
        self.assertIn("Publish an llms.txt manifest", document)
        self.assertIn('class="proactive"', document)

    def test_missing_proactive_section_is_skipped_not_an_error(self):
        report = json.loads(json.dumps(MINIMAL_REPORT))
        del report["proactive_recommendations"]
        document = render_dashboard(report)
        self.assertNotIn("Proactive Recommendations", document)
        self.assertEqual(parse(document).errors, [])

    def test_empty_proactive_list_is_skipped(self):
        report = json.loads(json.dumps(MINIMAL_REPORT))
        report["proactive_recommendations"] = []
        self.assertNotIn("Proactive Recommendations", render_dashboard(report))

    def test_report_with_no_findings_still_renders(self):
        report = {
            "site": "https://clean.test",
            "audited_at": "2026-01-01T00:00:00Z",
            "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
            "findings": [],
        }
        document = render_dashboard(report)
        self.assertEqual(parse(document).errors, [])
        self.assertIn("No findings recorded", document)

    def test_is_self_contained_with_no_external_requests(self):
        checker = parse(render_dashboard(MINIMAL_REPORT))
        # The only absolute URL allowed is the audited site's own link in the header.
        self.assertEqual(checker.external_refs, ["https://acme.test"])
        self.assertNotIn("<link", render_dashboard(MINIMAL_REPORT))

    def test_titles_are_html_escaped(self):
        report = json.loads(json.dumps(MINIMAL_REPORT))
        report["findings"][0]["title"] = '<img src=x onerror="alert(1)">'
        document = render_dashboard(report)
        self.assertNotIn('<img src=x', document)
        self.assertIn("&lt;img src=x", document)

    def test_cli_writes_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            out_path = Path(tmp) / "dashboard.html"
            report_path.write_text(json.dumps(MINIMAL_REPORT), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(report_path), "--output", str(out_path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out_path.exists())
            document = out_path.read_text(encoding="utf-8")
            self.assertTrue(document.startswith("<!DOCTYPE html>"))
            self.assertIn("AI assistant crawler is disallowed in robots.txt", document)
            self.assertEqual(json.loads(proc.stdout)["findings_rendered"], 2)


if __name__ == "__main__":
    unittest.main()
