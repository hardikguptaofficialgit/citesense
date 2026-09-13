"""
test_site_inventory.py -- Tests SiteInventory parsing, single-pass crawl caching,
and structured element extraction.
"""
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/crawl-render-audit/scripts"))

from site_inventory import (
    SiteInventory,
    analyze_page_html,
    classify_page_purpose,
    classify_resource_type,
    parse_jsonld,
)


class SiteInventoryTests(unittest.TestCase):

    def test_jsonld_parsing_and_flattening(self):
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Organization",
                        "name": "Acme Inc",
                        "url": "https://example.com",
                        "sameAs": ["https://twitter.com/acme", "https://wikidata.org/wiki/Q12345"]
                    },
                    {
                        "@type": "WebSite",
                        "name": "Acme Official Site"
                    }
                ]
            }
            </script>
        </head>
        </html>
        """
        entities, errors = parse_jsonld(html)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(entities), 2)
        org = [e for e in entities if e.get("@type") == "Organization"][0]
        self.assertEqual(org["name"], "Acme Inc")
        self.assertEqual(len(org["sameAs"]), 2)

    def test_page_purpose_classification(self):
        self.assertEqual(classify_page_purpose("https://example.com/", "Acme Home", "Welcome to Acme", "text"), "homepage")
        self.assertEqual(classify_page_purpose("https://example.com/in/", "Acme India", "Welcome", "text"), "homepage")
        self.assertEqual(classify_page_purpose("https://example.com/pricing", "Pricing Plans", "Choose a Plan", "text"), "product_pricing")
        self.assertEqual(classify_page_purpose("https://example.com/products/widget", "Widget", "Widget", ""), "product_landing")
        self.assertEqual(classify_page_purpose("https://example.com/docs/intro", "Documentation", "Getting Started", "text"), "article_docs")
        self.assertEqual(classify_page_purpose("https://example.com/contact-us", "Contact Support", "Get in touch", "text"), "contact_support")

    def test_non_html_resources_are_not_page_documents(self):
        self.assertEqual(classify_resource_type("https://example.com/assets/all-products.svg"), "svg")
        self.assertEqual(classify_resource_type("https://example.com/app", "text/css"), "css")
        snapshot = analyze_page_html(
            "https://example.com/assets/all-products.svg",
            "<svg><title>Products</title></svg>",
            "https://example.com/assets/all-products.svg",
            200,
            0.1,
            content_type="image/svg+xml",
            resource_type="svg",
        )
        self.assertFalse(snapshot["is_page"])
        self.assertEqual(snapshot["resource_type"], "svg")

    def test_authentication_shell_is_inconclusive(self):
        snapshot = analyze_page_html(
            "https://example.com/login",
            "<html><body><form><input name='email'><input type='password'>"
            "<button>Sign in</button></form></body></html>",
            "https://example.com/login",
            200,
            0.1,
        )
        self.assertTrue(snapshot["inconclusive"])
        self.assertEqual(snapshot["access_status"], "authentication-required")

    def test_interactive_and_media_element_extraction(self):
        html = """
        <html>
        <head><title>Dashboard</title></head>
        <body>
            <h1>Main Console</h1>
            <button type='button'>Export Data</button>
            <div role='button'>Toggle View</div>
            <a href='/pricing'>View Pricing</a>
            <img src='/logo.png' alt='Acme Logo' />
            <img src='/decor.png' />
            <canvas id='chart' width='300' height='200'></canvas>
        </body>
        </html>
        """
        snap = analyze_page_html("https://example.com/dash", html, "https://example.com/dash", 200, 0.15)
        buttons = snap["interactive_elements"]["buttons"]
        self.assertEqual(len(buttons), 2)
        self.assertTrue(any(b["text"] == "Export Data" for b in buttons))
        self.assertTrue(any(b["text"] == "Toggle View" for b in buttons))

        cta_links = snap["interactive_elements"]["cta_links"]
        self.assertEqual(len(cta_links), 1)
        self.assertEqual(cta_links[0]["text"], "View Pricing")

        images = snap["media_elements"]["images"]
        self.assertEqual(len(images), 2)
        self.assertTrue(images[0]["has_alt"])
        self.assertFalse(images[1]["has_alt"])
        self.assertEqual(snap["media_elements"]["canvas_count"], 1)

    def test_inventory_serialization_roundtrip(self):
        inv = SiteInventory("https://testbrand.com")
        inv.origin = "https://testbrand.com"
        inv.ground_truth = {"brand_name": "TestBrand", "category": "SaaS", "location": "US", "key_facts": {"founding_year": "2020"}}
        inv.pages["https://testbrand.com/"] = {
            "url": "https://testbrand.com/",
            "final_url": "https://testbrand.com/",
            "status_code": 200,
            "title": "TestBrand Home",
            "word_count": 100
        }

        d = inv.to_dict()
        restored = SiteInventory.from_dict(d)
        self.assertEqual(restored.seed_url, "https://testbrand.com/")
        self.assertEqual(restored.ground_truth["brand_name"], "TestBrand")
        self.assertIn("https://testbrand.com/", restored.pages)


if __name__ == "__main__":
    unittest.main()
