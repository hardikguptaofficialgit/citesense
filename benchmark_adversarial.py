"""Deterministic, dependency-free adversarial benchmark for the CiteSense pipeline.

Run from the repository with:
    PYTHONPATH=src python benchmark_adversarial.py --output benchmark-results.json

The HTTP server is local and disposable. It exercises the real orchestrator without
depending on public-site availability, search engines, browser automation, or an LLM.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from contextlib import ExitStack
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
for _directory in (
    ROOT / "skills" / "audit-orchestrator" / "scripts",
    ROOT / "skills" / "crawl-render-audit" / "scripts",
):
    sys.path.insert(0, str(_directory))

from citesense.api import run_full_audit
from scored import compute_citability_score
from site_inventory import (
    analyze_page_html,
    classify_page_purpose,
    classify_resource_type,
)

_REAL_GETADDRINFO = socket.getaddrinfo


CATEGORIES = [
    "saas", "ecommerce", "restaurant", "hotel", "healthcare", "university",
    "course_platform", "news", "documentation", "finance", "government",
    "nonprofit", "community", "product_marketing", "portfolio", "directory",
    "spa", "knowledge_base",
]
TIERS = ("strong", "average", "poor")
NONCOMMERCIAL = {
    "restaurant", "hotel", "healthcare", "university", "course_platform", "news",
    "documentation", "government", "nonprofit", "community", "portfolio",
    "directory", "knowledge_base",
}
COMMERCIAL = {"saas", "ecommerce", "finance", "product_marketing", "spa"}


def _schema(category: str, tier: str) -> str:
    name = category.replace("_", " ").title()
    if tier == "poor":
        return ""
    same_as = (
        ',"sameAs":["https://www.wikidata.org/wiki/Q1"]'
        if tier == "strong" else ""
    )
    return (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Organization",'
        f'"name":"{name} Example","url":"http://127.0.0.1/"'
        f'{same_as}}}'
        "</script>"
    )


def _page(category: str, tier: str, route: str) -> bytes:
    name = category.replace("_", " ").title()
    if tier == "poor":
        return (
            f"<!doctype html><html><head><title>{name}</title></head>"
            f"<body><p>Welcome to {name}. Contact us for more information.</p>"
            "<a href='/about'>About</a></body></html>"
        ).encode()

    commercial = category in COMMERCIAL
    route_title = {
        "pricing": "Pricing and Plans",
        "products": "Products and Services",
        "programs": "Programs and Courses",
        "articles": "Articles and Research",
        "docs": "Developer Documentation",
        "about": "About and Contact",
    }.get(route, name)
    links = [
        ("/", "Home"), ("/about", "About"), ("/contact", "Contact"),
        ("/products" if commercial else "/programs", "Offering"),
        ("/all-products.svg", "Asset"),
    ]
    if commercial:
        links.append(("/pricing", "Pricing"))
    else:
        links.append(("/articles" if category in {"news", "documentation", "knowledge_base"} else "/programs", "Content"))
    nav = "".join(f"<a href='{href}'>{label}</a>" for href, label in links)
    pricing_schema = ""
    pricing_text = ""
    if route == "pricing" and commercial:
        pricing_text = " Plans start at $19 per month. Choose a subscription."
        pricing_schema = (
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"Product","name":"Example Plan","offers":{"@type":"Offer",'
            '"price":"19","priceCurrency":"USD"}}</script>'
        )
    body = (
        f"<h1>{route_title}</h1><p>{name} Example provides clear information "
        f"for its audience, services, contact details, and location.{pricing_text}</p>"
        "<button>Get started</button><address>1 Example Street</address>"
        "<a href='mailto:hello@example.test'>hello@example.test</a>"
    )
    if tier == "average":
        body = f"<h1>{route_title}</h1><p>{name} provides some information.</p>"
    return (
        "<!doctype html><html><head><title>"
        f"{route_title} | {name}</title><meta name='description' content='Information about {name}'>"
        "<meta name='viewport' content='width=device-width'></head><body>"
        f"<nav>{nav}</nav>{_schema(category, tier)}{pricing_schema}<main>{body}</main>"
        "</body></html>"
    ).encode()


def _handler(mode: str, category: str = "", tier: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # Keep benchmark output deterministic.
            return

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /\n" if mode == "robots_blocked" else b"User-agent: *\nDisallow:\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(body)
                return
            if mode == "challenge":
                self.send_response(403)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Checking your browser. Verify you are human.</body></html>")
                return
            if mode == "empty":
                self.send_response(200)
                self.end_headers()
                return
            if mode == "binary":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                self.wfile.write(b"\x00\x01\x02not-html")
                return
            if mode == "redirect" and path == "/":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            if mode == "login":
                body = b"<html><body><form><input name='email'><button>Sign in</button></form></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)
                return
            if mode == "redirect":
                body = _page("saas", "strong", "final")
            elif mode == "normal":
                route = path.strip("/").split("/")[-1] or "home"
                body = _page(category, tier, route)
            else:
                body = b""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _audit_server(mode: str, category: str = "", tier: str = "") -> dict:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(mode, category, tier))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def resolve_fixture(host, port, *args, **kwargs):
            if host == "127.0.0.1":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
            return _REAL_GETADDRINFO(host, port, *args, **kwargs)

        # The fixture server is intentionally loopback-only. Permit only this
        # deterministic test transport; production safe_fetch remains fail-closed.
        with ExitStack() as stack:
            stack.enter_context(patch("audit_common.socket.getaddrinfo", side_effect=resolve_fixture))
            for module in list(sys.modules.values()):
                if module is None:
                    continue
                target_validator = getattr(module, "_fetch_target_error", None)
                if target_validator is not None:
                    stack.enter_context(
                        patch.object(
                            module,
                            "_fetch_target_error",
                            side_effect=lambda url, original=target_validator: (
                                None
                                if urlparse(url).hostname == "127.0.0.1"
                                and urlparse(url).port == server.server_port
                                else original(url)
                            ),
                        )
                    )
            return run_full_audit(
                f"http://127.0.0.1:{server.server_port}/",
                max_pages=5,
                timeout=2,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _row(category: str, tier: str, report: dict) -> dict:
    summary = report.get("summary", {})
    breakdown = summary.get("citability_score_breakdown", {})
    return {
        "category": category,
        "quality_tier": tier,
        "pages": report.get("access_summary", {}).get("pages_sampled", 0),
        "findings": summary.get("total_findings", 0),
        "high": summary.get("high", 0),
        "medium": summary.get("medium", 0),
        "low": summary.get("low", 0),
        "score": summary.get("citability_score"),
        "breakdown": breakdown,
    }


def _check_evidence(report: dict) -> list[str]:
    ledger_ids = {
        entry.get("evidence_id")
        for entry in report.get("evidence_ledger", [])
        if isinstance(entry, dict)
    }
    errors = []
    for finding in report.get("findings", []):
        refs = finding.get("evidence_refs", [])
        if not isinstance(refs, list) or not set(refs) <= ledger_ids:
            errors.append(f"{finding.get('id')}: unresolved evidence_refs")
    return errors


def run(output: Path | None = None) -> dict:
    rows = []
    reports = {}
    errors = []
    for category in CATEGORIES:
        for tier in TIERS:
            report = _audit_server("normal", category, tier)
            key = f"{category}:{tier}"
            reports[key] = report
            rows.append(_row(category, tier, report))
            errors.extend(f"{key}: {error}" for error in _check_evidence(report))
            if category in NONCOMMERCIAL:
                for finding in report.get("findings", []):
                    if "product-offer-missing" in finding.get("fingerprint", ""):
                        errors.append(f"{key}: commercial Product finding on noncommercial site")
            resource_urls = ("all-products.svg", "logo.png", "site.css", "app.js", "manual.pdf", "font.woff2")
            for finding in report.get("findings", []):
                if any(token in finding.get("evidence", "") for token in resource_urls):
                    errors.append(f"{key}: resource produced page finding")

    access = {}
    for mode in ("robots_blocked", "challenge", "empty", "binary", "redirect", "login"):
        report = _audit_server(mode)
        access[mode] = {
            "pages": report.get("access_summary", {}).get("pages_sampled", 0),
            "readable": report.get("access_summary", {}).get("readable_pages", 0),
            "findings": report.get("summary", {}).get("total_findings", 0),
            "score": report.get("summary", {}).get("citability_score"),
            "trust_or_answerability_findings": [
                f["title"] for f in report.get("findings", [])
                if f.get("category") in {"trust", "citation-answerability"}
            ],
        }
        if mode == "login" and (
            report.get("summary", {}).get("total_findings", 0)
            or access[mode]["trust_or_answerability_findings"]
        ):
            errors.append("login/auth shell produced site-wide findings")

    resource_inputs = {
        "html": ("https://example.test/page", "text/html"),
        "fragment": ("https://example.test/fragments/hero", "text/html"),
        "svg": ("https://example.test/resource.svg", "image/svg+xml"),
        "png": ("https://example.test/resource.png", "image/png"),
        "jpg": ("https://example.test/resource.jpg", "image/jpeg"),
        "webp": ("https://example.test/resource.webp", "image/webp"),
        "css": ("https://example.test/resource.css", "text/css"),
        "js": ("https://example.test/resource.js", "text/javascript"),
        "pdf": ("https://example.test/resource.pdf", "application/pdf"),
        "woff2": ("https://example.test/resource.woff2", "font/woff2"),
        "json": ("https://example.test/resource.json", "application/json"),
        "bin": ("https://example.test/resource.bin", "application/octet-stream"),
    }
    resource_cases = {
        ext: classify_resource_type(url, content_type)
        for ext, (url, content_type) in resource_inputs.items()
    }
    resource_findings = []
    for ext, resource_type in resource_cases.items():
        resource_url = resource_inputs[ext][0]
        snapshot = analyze_page_html(
            resource_url, "binary", resource_url,
            200, 0.01, content_type=resource_type, resource_type=resource_type,
        )
        if snapshot.get("is_page") and resource_type != "html_document":
            resource_findings.append(resource_type)

    purpose_cases = {
        "homepage": classify_page_purpose("https://x.test/in/", "Home", "Welcome", ""),
        "commercial": classify_page_purpose("https://x.test/solutions", "Solutions", "Platform", ""),
        "product": classify_page_purpose("https://x.test/products/widget", "Widget", "Widget", ""),
        "pricing": classify_page_purpose("https://x.test/pricing", "Pricing Plans", "Choose a Plan", ""),
        "shop": classify_page_purpose("https://x.test/shop", "Shop", "", ""),
        "article": classify_page_purpose("https://x.test/blog/2026/story", "Story", "Story", ""),
        "docs": classify_page_purpose("https://x.test/docs/api", "API Docs", "API", ""),
        "contact": classify_page_purpose("https://x.test/contact", "Contact", "Contact", ""),
        "fragment": classify_page_purpose("https://x.test/fragments/hero", "Hero", "Hero", ""),
    }
    if purpose_cases["shop"] == "product_pricing":
        errors.append("shop was classified as product_pricing")
    if purpose_cases["product"] == "product_pricing":
        errors.append("product landing was classified as product_pricing")
    if purpose_cases["commercial"] == "product_pricing":
        errors.append("general commercial page was classified as product_pricing")
    if purpose_cases["fragment"] != "html_fragment":
        errors.append("HTML fragment was not classified as html_fragment")
    duplicate_report = {
        "findings": [
            {"fingerprint": "same-root", "severity": "high", "status": "confirmed"},
            {"fingerprint": "same-root", "severity": "high", "status": "confirmed"},
        ]
    }
    duplicate_score = compute_citability_score(duplicate_report)
    status_scores = {
        status: compute_citability_score({
            "findings": [{
                "fingerprint": status,
                "severity": "high",
                "status": status,
            }]
        })
        for status in ("confirmed", "likely-risk", "inconclusive", "not-assessed", "proactive")
    }
    results = {
        "rows": rows,
        "access_cases": access,
        "resource_cases": resource_cases,
        "resource_page_failures": resource_findings,
        "purpose_cases": purpose_cases,
        "duplicate_score": duplicate_score,
        "status_scores": status_scores,
        "evidence_errors": errors,
        "reports": reports,
    }
    if output:
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.output)
    for row in result["rows"]:
        print(
            f"{row['category']:18} {row['quality_tier']:7} "
            f"{row['pages']:>2} {row['findings']:>2} {row['high']:>2} "
            f"{row['medium']:>2} {row['low']:>2} {str(row['score']):>3}"
        )
    print(json.dumps({
        "access_cases": result["access_cases"],
        "resource_cases": result["resource_cases"],
        "resource_page_failures": result["resource_page_failures"],
        "purpose_cases": result["purpose_cases"],
        "duplicate_score": result["duplicate_score"],
        "evidence_errors": result["evidence_errors"],
    }, indent=2))
