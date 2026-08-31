#!/usr/bin/env python3
"""
render_and_data_scan.py -- Evaluates structured data, render gaps, and fact extractability.
Emits structured CandidateFindings and diagnostic details without false positives.
"""
import os
import sys
import json
import re
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from audit_common import visible_text, canonicalize, safe_fetch, DEFAULT_TIMEOUT
from models import create_candidate_finding, CandidateFinding
from site_inventory import SiteInventory, get_or_crawl_inventory

REQUIRED_SCHEMA_FIELDS = {
    "Organization": ["name", "url"],
    "LocalBusiness": ["name", "address"],
    "Product": ["name"],
    "Offer": ["price", "priceCurrency"],
    "Article": ["headline", "datePublished"],
    "NewsArticle": ["headline", "datePublished"],
    "FAQPage": ["mainEntity"],
}


def schema(html: str, url: str, raw: str) -> Dict[str, Any]:
    """Backward-compatible helper for legacy test suites and schema introspection."""
    from site_inventory import parse_jsonld, extract_jsonld_blocks
    parsed, errors = parse_jsonld(html)
    results = []
    identities = []
    for e in parsed:
        ts = e.get("@type", [])
        ts = ts if isinstance(ts, list) else [ts]
        for t in ts:
            if t in REQUIRED_SCHEMA_FIELDS:
                results.append({"type": t, "missing_important_fields": [f for f in REQUIRED_SCHEMA_FIELDS[t] if not e.get(f)], "id": e.get("@id")})
        if any(t in ("Organization", "LocalBusiness", "Corporation") for t in ts):
            identities.append({"name": e.get("name"), "url": e.get("url"), "sameAs": e.get("sameAs", []), "@id": e.get("@id")})
    names = [x["name"] for x in identities if x.get("name")]
    visible_name_consistency = [n for n in names if n.lower() not in raw.lower()]
    canon = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', html, re.I)
    canonical = canonicalize(url, canon.group(1).strip()) if canon else None
    return {
        "jsonld_blocks_found": len(extract_jsonld_blocks(html)),
        "jsonld_parse_errors": errors,
        "entities": len(parsed),
        "validation": results,
        "organization_identity": identities,
        "organization_names_not_visible": visible_name_consistency,
        "canonical": canonical,
        "canonical_matches_fetched_url": canonicalize(url, url) == canonical if canonical else None,
        "duplicate_entity_ids": sorted({e.get("@id") for e in parsed if e.get("@id") and sum(1 for z in parsed if z.get("@id") == e.get("@id")) > 1})
    }



def evaluate_page_render_and_data(page_snap: Dict[str, Any], is_root: bool = False) -> List[Dict[str, Any]]:
    """Analyzes a single page snapshot for structured data, metadata, and extractability findings."""
    findings = []
    url = page_snap.get("final_url") or page_snap.get("url", "")
    raw_html = page_snap.get("raw_html", "")
    status_code = page_snap.get("status_code", 0)

    # Inconclusive/fetch failure: never emit defect findings without a readable page
    if page_snap.get("inconclusive") or status_code != 200 or not raw_html:
        return []

    raw_text = page_snap.get("visible_text", "")
    words = page_snap.get("word_count", 0)
    title = page_snap.get("title", "")
    meta_desc = page_snap.get("meta_description", "")
    canonical = page_snap.get("canonical_url")
    purpose = page_snap.get("page_purpose", "general")
    jsonld_parsed = page_snap.get("jsonld_parsed", [])
    jsonld_errors = page_snap.get("jsonld_errors", [])
    images = page_snap.get("media_elements", {}).get("images", [])
    canvas_count = page_snap.get("media_elements", {}).get("canvas_count", 0)

    # 1. JSON-LD Syntax Errors
    if jsonld_errors:
        err_details = "; ".join([f"Block {e.get('block_index')}: {e.get('error')}" for e in jsonld_errors[:3]])
        f = create_candidate_finding(
            title="Syntax error in JSON-LD structured data script",
            category="structured-data",
            severity="medium",
            url=url,
            observation=f"Found {len(jsonld_errors)} malformed JSON-LD script block(s): {err_details}.",
            method="jsonld_parser",
            source_skill="crawl-render-audit",
            action_summary="Fix JSON-LD syntax errors to ensure search and AI parsers can read metadata.",
            action_priority="medium",
            action_how_to_fix="Validate JSON-LD blocks with a JSON validator and correct syntax issues like trailing commas or unescaped quotes.",
            fingerprint="schema:syntax-error",
            status="confirmed",
            confidence="high",
            impact="medium"
        )
        findings.append(f.to_dict())

    # 2. Schema Validation (Organization, Product, Offer, etc.)
    types_found = set()
    identities = []
    validation_issues = []

    for ent in jsonld_parsed:
        t = ent.get("@type", "")
        ts = t if isinstance(t, list) else [t]
        for type_name in ts:
            types_found.add(type_name)
            if type_name in REQUIRED_SCHEMA_FIELDS:
                missing = [f for f in REQUIRED_SCHEMA_FIELDS[type_name] if not ent.get(f)]
                if missing:
                    validation_issues.append(f"{type_name} missing {', '.join(missing)}")
            if type_name in ("Organization", "LocalBusiness", "Corporation", "Brand"):
                identities.append(ent)

    # Missing Organization schema on Root/Homepage
    if is_root or purpose == "homepage":
        if not identities:
            f = create_candidate_finding(
                title="Missing Schema.org Organization structured data on root landing page",
                category="structured-data",
                severity="medium",
                url=url,
                observation=f"Root homepage contains 0 Organization or LocalBusiness JSON-LD schema blocks.",
                method="jsonld_schema_extractor",
                source_skill="crawl-render-audit",
                action_summary="Add Organization JSON-LD markup to the homepage.",
                action_priority="medium",
                action_how_to_fix="Add a JSON-LD script on the homepage declaring @type 'Organization' with name, url, logo, and sameAs links to authoritative profiles.",
                fingerprint="schema:root-organization-missing",
                status="confirmed",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())
        else:
            # Check sameAs disambiguation on organization
            has_same_as = any(bool(ident.get("sameAs")) for ident in identities)
            if not has_same_as:
                f = create_candidate_finding(
                    title="Organization JSON-LD lacks sameAs authority and disambiguation links",
                    category="structured-data",
                    severity="low",
                    url=url,
                    observation=f"Organization schema exists but does not include 'sameAs' URIs pointing to official Wikipedia, Wikidata, LinkedIn, or social profiles.",
                    method="jsonld_schema_extractor",
                    source_skill="crawl-render-audit",
                    action_summary="Add sameAs URLs to Organization JSON-LD.",
                    action_priority="low",
                    action_how_to_fix="Include official external profile URLs (Wikipedia, Wikidata, Crunchbase, GitHub) in the Organization sameAs array.",
                    fingerprint="schema:organization-missing-sameas",
                    status="confirmed",
                    confidence="high",
                    impact="low"
                )
                findings.append(f.to_dict())

    # Missing Product/Offer on commercial product or pricing page
    if purpose == "product_pricing":
        has_product_or_offer = any(t in ("Product", "Offer", "SoftwareApplication", "Service") for t in types_found)
        if not has_product_or_offer:
            f = create_candidate_finding(
                title="Missing Schema.org Product and Offer structured data on commercial page",
                category="structured-data",
                severity="high",
                url=url,
                observation=f"Commercial/product page ({url}) contains no Product or Offer structured data to convey machine-readable pricing and features.",
                method="jsonld_schema_extractor",
                source_skill="crawl-render-audit",
                action_summary="Add Schema.org Product and Offer JSON-LD to commercial and pricing pages.",
                action_priority="high",
                action_how_to_fix="Embed JSON-LD with @type 'Product' or 'Service' and nested 'Offer' elements defining prices, currency, billing cycles, and availability.",
                fingerprint=f"schema:product-offer-missing:{urlparse(url).path}",
                status="confirmed",
                confidence="high",
                impact="high"
            )
            findings.append(f.to_dict())

    # Schema field completeness issues
    if validation_issues:
        f = create_candidate_finding(
            title="Incomplete Schema.org entity fields in JSON-LD markup",
            category="structured-data",
            severity="medium",
            url=url,
            observation=f"Schema entities are missing required properties: {'; '.join(validation_issues[:3])}.",
            method="schema_field_validator",
            source_skill="crawl-render-audit",
            action_summary="Populate required Schema.org properties.",
            action_priority="medium",
            action_how_to_fix="Ensure all required fields (e.g. name, price, priceCurrency, headline) are populated in declared Schema.org blocks.",
            fingerprint="schema:missing-required-fields",
            status="confirmed",
            confidence="high",
            impact="medium"
        )
        findings.append(f.to_dict())

    # 3. Fact Extractability & Render Gap
    # Note: JavaScript usage alone is NOT a defect. Only flag if raw HTML is an empty shell lacking core content.
    if words < 30 and len(raw_html) > 1000:
        f = create_candidate_finding(
            title="Client-side rendering gap: raw HTML contains minimal text content",
            category="render-gap",
            severity="high",
            url=url,
            observation=f"Raw HTML yields only {words} words of visible text. Search crawlers and AI bots that do not execute client JS cannot extract core brand facts.",
            method="raw_vs_rendered_wordcount_inspection",
            source_skill="crawl-render-audit",
            action_summary="Implement server-side rendering (SSR) or static pre-rendering for core content.",
            action_priority="high",
            action_how_to_fix="Use static site generation (SSG) or SSR so that primary textual facts and headers are present in initial HTTP responses without JS execution.",
            fingerprint=f"render:empty-raw-html-gap:{urlparse(url).path or 'root'}",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())

    # 4. Media-Locked Content
    if canvas_count > 0 and words < 50:
        f = create_candidate_finding(
            title="Facts potentially locked inside HTML5 Canvas without textual fallback",
            category="fact-extractability",
            severity="medium",
            url=url,
            observation=f"Page utilizes {canvas_count} <canvas> element(s) with minimal companion text ({words} words), preventing machine extraction of displayed data.",
            method="media_element_inspection",
            source_skill="crawl-render-audit",
            action_summary="Provide accessible HTML text or structured data fallbacks for canvas graphics.",
            action_priority="medium",
            action_how_to_fix="Accompany canvas charts/diagrams with summary data tables or structured JSON-LD entities.",
            fingerprint="extractability:canvas-locked-content",
            status="likely-risk",
            confidence="medium",
            impact="medium"
        )
        findings.append(f.to_dict())

    # 5. Core HTML Metadata Check
    if not title:
        f = create_candidate_finding(
            title="Missing HTML document <title> tag",
            category="structured-data",
            severity="high",
            url=url,
            observation="Page HTML contains no <title> tag.",
            method="html_meta_inspector",
            source_skill="crawl-render-audit",
            action_summary="Add a descriptive <title> tag.",
            action_priority="high",
            action_how_to_fix="Add a unique, informative <title> tag inside the <head> element.",
            fingerprint="meta:missing-title",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())

    if (is_root or purpose in ("homepage", "product_pricing")) and not meta_desc:
        f = create_candidate_finding(
            title="Missing meta description on key landing page",
            category="structured-data",
            severity="medium",
            url=url,
            observation="Page HTML contains no <meta name=\"description\"> tag, depriving search and AI engines of an authoritative snippet summary.",
            method="html_meta_inspector",
            source_skill="crawl-render-audit",
            action_summary="Add an informative meta description tag.",
            action_priority="medium",
            action_how_to_fix="Add <meta name=\"description\" content=\"...\"> summarizing the brand and page offerings.",
            fingerprint="meta:missing-description",
            status="confirmed",
            confidence="high",
            impact="medium"
        )
        findings.append(f.to_dict())

    return findings


def evaluate_render_and_data_scan(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """Evaluates all pages in the SiteInventory for structured data and render issues."""
    all_findings = []
    for i, (url, snap) in enumerate(inventory.pages.items()):
        is_root = (i == 0 or url == inventory.seed_url or url == inventory.origin or url == inventory.origin + "/")
        page_findings = evaluate_page_render_and_data(snap, is_root=is_root)
        all_findings.extend(page_findings)
    return all_findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: render_and_data_scan.py <url_or_inventory_json> [--findings-only]"})); sys.exit(1)

    target = sys.argv[1]
    inventory = get_or_crawl_inventory(target)
    findings = evaluate_render_and_data_scan(inventory)

    if "--findings-only" in sys.argv:
        print(json.dumps(findings, indent=2))
    else:
        out = {
            "site": inventory.origin,
            "pages_analyzed": len(inventory.pages),
            "findings": findings
        }
        seed_page = inventory.pages.get(inventory.seed_url) or next(iter(inventory.pages.values()), {})
        if seed_page.get("status_code") != 200:
            out["error"] = "unavailable; no finding should be emitted without other evidence"
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
