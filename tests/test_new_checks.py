"""
test_new_checks.py -- Cover for the checks added to close Progress.md items 18 and 19:
image-locked facts (Appendix C) and the engagement/personalization half (Appendix E).

Each check is tested in both directions: it fires when the defect is real, and stays silent
when it is not. The silent case is the one that matters -- these categories are where a
careless check manufactures findings on healthy sites.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for sub in ("crawl-render-audit", "engagement-audit"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

from site_inventory import SiteInventory, analyze_page_html
from render_and_data_scan import evaluate_page_render_and_data
from engagement_scan import evaluate_site_level_engagement
from crawlability_check import evaluate_crawlability


def page(url, body, head="<title>T</title>"):
    html = f"<html><head>{head}</head><body>{body}</body></html>"
    return analyze_page_html(url, html, url, 200, 0.1)


def inventory(pages, brand="Acme", source="organization_schema"):
    inv = SiteInventory("https://acme.test")
    inv.origin = "https://acme.test"
    for u, snap in pages:
        inv.pages[u] = snap
    inv.ground_truth = {"brand_name": brand, "brand_name_source": source, "key_facts": {}}
    return inv


class ImageLockedFactTests(unittest.TestCase):
    """Item 18 -- the `images` data was collected but never used by any finding."""

    def test_decorative_alt_empty_is_not_a_defect(self):
        # alt="" is the CORRECT marking for a decorative image. Flagging it would fire on
        # virtually every well-built site.
        body = "".join(f'<img src="/icon{i}.png" alt="">' for i in range(8)) + "<p>Body copy here.</p>"
        findings = evaluate_page_render_and_data(page("https://acme.test/x", body))
        self.assertEqual([f for f in findings if f["category"] == "fact-extractability"], [])

    def test_missing_alt_attribute_is_flagged(self):
        body = "".join(f'<img src="/chart{i}.png">' for i in range(8)) + "<p>Body copy.</p>"
        findings = evaluate_page_render_and_data(page("https://acme.test/x", body))
        hits = [f for f in findings if f["fingerprint"] == "extractability:images-without-alt"]
        self.assertEqual(len(hits), 1)

    def test_described_images_are_not_flagged(self):
        body = "".join(f'<img src="/p{i}.png" alt="Pro plan costs $49 per month">' for i in range(8))
        findings = evaluate_page_render_and_data(page("https://acme.test/x", body))
        self.assertEqual([f for f in findings if f["fingerprint"] == "extractability:images-without-alt"], [])

    def test_few_images_do_not_trip_the_threshold(self):
        body = '<img src="/a.png"><img src="/b.png"><p>Text.</p>'
        findings = evaluate_page_render_and_data(page("https://acme.test/x", body))
        self.assertEqual([f for f in findings if f["category"] == "fact-extractability"], [])


class MoneyPagePriceTests(unittest.TestCase):
    """Item 18 -- the highest-value instance: a price that exists only inside an image."""

    def test_pricing_page_with_no_price_text_is_flagged(self):
        body = '<h1>Plans</h1><img src="/tier1.png"><img src="/tier2.png"><img src="/tier3.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/pricing", body))
        hits = [f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "high")

    def test_pricing_page_with_a_price_in_text_is_not_flagged(self):
        body = '<h1>Plans</h1><p>From $49 per month.</p><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/pricing", body))
        self.assertEqual([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]], [])

    def test_pricing_page_with_offer_schema_is_not_flagged(self):
        body = ('<h1>Plans</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
                '<script type="application/ld+json">'
                '{"@type":"Offer","price":"49","priceCurrency":"USD"}</script>')
        findings = evaluate_page_render_and_data(page("https://acme.test/pricing", body))
        self.assertEqual([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]], [])

    def test_product_catalogue_page_is_not_price_checked(self):
        # "/products/" is a catalogue, not a pricing route. Mozilla's free-products page was
        # flagged here, and the English-only "free" test could not read its German copy.
        body = '<h1>Our products</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/de/products/", body))
        self.assertEqual([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]], [])

    def test_explicit_pricing_route_is_still_checked(self):
        body = '<h1>Plans</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/plans", body))
        self.assertEqual(len([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]]), 1)

    def test_commercial_word_inside_an_article_slug_is_not_a_pricing_route(self):
        # Live FP: stripe.com/in/newsroom/news/stripe-openai-instant-checkout matched the token
        # "checkout" inside its slug. Only whole path SEGMENTS count.
        body = '<h1>Announcement</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        url = "https://acme.test/in/newsroom/news/acme-partner-instant-checkout"
        findings = evaluate_page_render_and_data(page(url, body))
        self.assertEqual([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]], [])

    def test_localized_pricing_segment_is_still_checked(self):
        body = '<h1>Pricing</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/in/pricing", body))
        self.assertEqual(len([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]]), 1)

    def test_non_commercial_page_is_never_price_checked(self):
        body = '<h1>Docs</h1><img src="/a.png"><img src="/b.png"><img src="/c.png">'
        findings = evaluate_page_render_and_data(page("https://acme.test/docs/intro", body))
        self.assertEqual([f for f in findings if "money-page-price-not-in-text" in f["fingerprint"]], [])


class ColdArrivalOrientationTests(unittest.TestCase):
    """Item 19 -- a visitor landing mid-site from an AI citation has no homepage context."""

    def test_deep_page_that_never_names_the_brand_is_flagged(self):
        inv = inventory([("https://acme.test/docs/guide",
                          page("https://acme.test/docs/guide", "<h1>Configuration</h1><p>Set the flag.</p>"))])
        hits = [f for f in evaluate_site_level_engagement(inv)
                if f["fingerprint"] == "engagement:deep-pages-anonymous"]
        self.assertEqual(len(hits), 1)

    def test_deep_page_naming_the_brand_is_not_flagged(self):
        inv = inventory([("https://acme.test/docs/guide",
                          page("https://acme.test/docs/guide", "<h1>Acme Configuration</h1><p>Set it.</p>"))])
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["fingerprint"] == "engagement:deep-pages-anonymous"], [])

    def test_shallow_pages_are_exempt(self):
        inv = inventory([("https://acme.test/about",
                          page("https://acme.test/about", "<h1>About</h1><p>No brand token here.</p>"))])
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["fingerprint"] == "engagement:deep-pages-anonymous"], [])

    def test_low_confidence_brand_name_suppresses_the_check(self):
        # A domain-label guess is not a solid enough basis to accuse a page of not naming itself.
        inv = inventory(
            [("https://acme.test/docs/guide", page("https://acme.test/docs/guide", "<h1>Config</h1>"))],
            source="domain_label",
        )
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["fingerprint"] == "engagement:deep-pages-anonymous"], [])


class SearchAndPersonalizationTests(unittest.TestCase):
    """Item 19 -- `personalization-readiness` was a declared category nothing ever emitted."""

    def test_missing_search_is_flagged(self):
        inv = inventory([("https://acme.test/", page("https://acme.test/", "<h1>Acme</h1>"))])
        hits = [f for f in evaluate_site_level_engagement(inv)
                if f["fingerprint"] == "engagement:no-site-search"]
        self.assertEqual(len(hits), 1)

    def test_search_input_suppresses_the_finding(self):
        inv = inventory([("https://acme.test/",
                          page("https://acme.test/", '<h1>Acme</h1><input type="search" name="q">'))])
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["fingerprint"] == "engagement:no-site-search"], [])

    def test_role_search_suppresses_the_finding(self):
        inv = inventory([("https://acme.test/",
                          page("https://acme.test/", '<h1>Acme</h1><form role="search"><input name="x"></form>'))])
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["fingerprint"] == "engagement:no-site-search"], [])

    def test_personalization_readiness_is_emitted_as_proactive_not_a_defect(self):
        inv = inventory([("https://acme.test/", page("https://acme.test/", "<h1>Acme</h1>"))])
        hits = [f for f in evaluate_site_level_engagement(inv)
                if f["category"] == "personalization-readiness"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["status"], "proactive")
        self.assertEqual(hits[0]["severity"], "low")

    def test_sign_in_affordance_suppresses_personalization_finding(self):
        inv = inventory([("https://acme.test/",
                          page("https://acme.test/", "<h1>Acme</h1><a href='/login'>Sign in</a>"))])
        self.assertEqual([f for f in evaluate_site_level_engagement(inv)
                          if f["category"] == "personalization-readiness"], [])

    def test_inconclusive_pages_produce_no_site_level_findings(self):
        inv = SiteInventory("https://acme.test")
        inv.origin = "https://acme.test"
        inv.pages["https://acme.test/"] = {"inconclusive": True, "status_code": 200}
        inv.ground_truth = {"brand_name": "Acme", "brand_name_source": "organization_schema"}
        self.assertEqual(evaluate_site_level_engagement(inv), [])

    def test_unreadable_crawl_does_not_infer_missing_sitemap(self):
        inv = SiteInventory("https://acme.test")
        inv.origin = "https://acme.test"
        inv.pages["https://acme.test/"] = {
            "inconclusive": True,
            "status_code": None,
        }
        inv.sitemaps = [{"url": "https://acme.test/sitemap.xml", "found": False}]
        findings = evaluate_crawlability(inv)
        self.assertNotIn("crawl:missing-xml-sitemap", {f.get("fingerprint") for f in findings})


if __name__ == "__main__":
    unittest.main()
