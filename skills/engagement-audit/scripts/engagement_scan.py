#!/usr/bin/env python3
"""
engagement_scan.py -- Comprehensive on-site engagement audit.
Evaluates orientation (H1/title/purpose), navigation, buttons/forms/CTAs, broken links,
mobile viewport, and personalization readiness. Emits structured CandidateFindings.
"""
import os
import sys
import json
import re
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from audit_common import safe_fetch, DEFAULT_TIMEOUT
from models import create_candidate_finding, CandidateFinding
from site_inventory import SiteInventory, get_or_crawl_inventory

MAX_BROKEN_LINKS_TO_CHECK = 8


def evaluate_page_engagement(page_snap: Dict[str, Any], is_root: bool = False) -> List[Dict[str, Any]]:
    """Evaluates a single page snapshot for engagement, orientation, and navigation findings."""
    findings = []
    url = page_snap.get("final_url") or page_snap.get("url", "")
    status_code = page_snap.get("status_code", 0)

    if page_snap.get("inconclusive") or status_code != 200 or not page_snap.get("raw_html"):
        return []

    title = page_snap.get("title", "")
    h1_texts = page_snap.get("h1_texts", [])
    headings = page_snap.get("headings", [])
    purpose = page_snap.get("page_purpose", "general")
    is_deep = page_snap.get("is_deep_page", False)
    viewport_present = page_snap.get("viewport_meta_present", False)
    internal_links = page_snap.get("internal_links", [])
    interactive = page_snap.get("interactive_elements", {})
    buttons = interactive.get("buttons", [])
    forms = interactive.get("forms", [])
    cta_links = interactive.get("cta_links", [])

    # 1. Orientation: H1 and Title Alignment
    if not h1_texts:
        f = create_candidate_finding(
            title="Missing primary H1 heading on landing page",
            category="orientation",
            severity="high",
            url=url,
            observation="Page lacks a primary <h1> heading tag to establish core topic and orientation for arriving visitors.",
            method="heading_structure_inspection",
            source_skill="engagement-audit",
            action_summary="Add a clear, descriptive <h1> heading.",
            action_priority="high",
            action_how_to_fix="Add a single <h1> heading tag at the top of the main content summarizing the page's purpose.",
            fingerprint="engagement:missing-h1",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())
    elif len(h1_texts) > 2:
        f = create_candidate_finding(
            title="Multiple competing <h1> headings cause ambiguous page hierarchy",
            category="orientation",
            severity="low",
            url=url,
            observation=f"Page defines {len(h1_texts)} separate <h1> tags ({'; '.join([h[:40] for h in h1_texts[:3]])}), diluting semantic structure.",
            method="heading_structure_inspection",
            source_skill="engagement-audit",
            action_summary="Consolidate heading hierarchy to a single primary <h1>.",
            action_priority="low",
            action_how_to_fix="Keep one top-level <h1> for the primary topic and convert subordinate headings to <h2> or <h3>.",
            fingerprint="engagement:multiple-h1",
            status="confirmed",
            confidence="high",
            impact="low"
        )
        findings.append(f.to_dict())

    # 2. Navigation & Next-Step Signals (Buttons, Forms, CTAs)
    total_actions = len(buttons) + len(forms) + len(cta_links)

    # On commercial/product/pricing pages, having zero actionable next steps is a major defect
    if purpose in ("product_pricing", "homepage") and total_actions == 0:
        f = create_candidate_finding(
            title="Commercial landing page lacks clear call-to-action buttons or interactive forms",
            category="navigation",
            severity="high",
            url=url,
            observation=f"Page classified as '{purpose}' contains 0 CTA buttons, 0 interactive forms, and 0 action links, creating a dead end for converting traffic.",
            method="interactive_element_analysis",
            source_skill="engagement-audit",
            action_summary="Add prominent primary call-to-action (CTA) buttons.",
            action_priority="high",
            action_how_to_fix="Add visually distinct CTA buttons (e.g. 'Get Started', 'View Pricing', 'Contact Sales') above and below the fold.",
            fingerprint=f"engagement:missing-cta:{urlparse(url).path or 'root'}",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())

    # Check for dead-end pages (< 3 internal links)
    if len(internal_links) < 2 and purpose != "contact_support":
        f = create_candidate_finding(
            title="Isolated page with insufficient internal navigation links",
            category="navigation",
            severity="medium",
            url=url,
            observation=f"Page contains only {len(internal_links)} internal link(s), leaving visitors with limited navigation pathways to explore the brand.",
            method="internal_link_density_check",
            source_skill="engagement-audit",
            action_summary="Incorporate related internal links and header/footer navigation.",
            action_priority="medium",
            action_how_to_fix="Add links to relevant documentation, related products, or category overview pages.",
            fingerprint="engagement:few-internal-links",
            status="likely-risk",
            confidence="medium",
            impact="medium"
        )
        findings.append(f.to_dict())

    # 3. Breadcrumbs on deep hierarchical pages
    # NOTE: Never flag breadcrumbs on root/shallow pages
    raw_html = page_snap.get("raw_html", "")
    has_breadcrumb = bool(re.search(r'(?is)breadcrumb', raw_html))
    if is_deep and not has_breadcrumb:
        f = create_candidate_finding(
            title="Deep hierarchical page lacks breadcrumb navigation trail",
            category="navigation",
            severity="low",
            url=url,
            observation=f"Page at deep route ({urlparse(url).path}) lacks breadcrumb UI or Schema.org BreadcrumbList markup for parent context.",
            method="breadcrumb_markup_inspector",
            source_skill="engagement-audit",
            action_summary="Add breadcrumb navigation trail with BreadcrumbList schema.",
            action_priority="low",
            action_how_to_fix="Add visual breadcrumb navigation and accompanying Schema.org BreadcrumbList JSON-LD to assist user orientation.",
            fingerprint="engagement:missing-breadcrumbs",
            status="likely-risk",
            confidence="medium",
            impact="low"
        )
        findings.append(f.to_dict())

    # 4. Mobile Responsiveness (Viewport meta)
    if not viewport_present:
        f = create_candidate_finding(
            title="Missing viewport meta tag hampers mobile user engagement",
            category="orientation",
            severity="high",
            url=url,
            observation="HTML <head> lacks <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">, causing mobile browsers to render desktop scale.",
            method="mobile_viewport_inspector",
            source_skill="engagement-audit",
            action_summary="Add responsive viewport meta tag to HTML head.",
            action_priority="high",
            action_how_to_fix="Insert <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"> into the document <head>.",
            fingerprint="engagement:missing-viewport-meta",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())

    return findings


def check_broken_links_sample(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """Samples internal links from SiteInventory and tests for actual 4xx/5xx broken links with redirect following."""
    findings = []
    sampled_links = []
    
    for snap in inventory.pages.values():
        for link in snap.get("internal_links", []):
            href = link.get("href")
            # robots.txt gates link probing too, not just page crawling
            if href and href not in sampled_links and not inventory.knows_url(href) and inventory.may_fetch(href):
                sampled_links.append(href)
            if len(sampled_links) >= MAX_BROKEN_LINKS_TO_CHECK:
                break
        if len(sampled_links) >= MAX_BROKEN_LINKS_TO_CHECK:
            break

    broken_links = []
    for link_url in sampled_links:
        status, _, final_url, redirect_chain, _, _ = safe_fetch(link_url, method="GET", timeout=5)
        # Only treat 4xx or 5xx as confirmed broken. If it redirects to 200, it is NOT broken!
        if status is not None and status >= 400:
            broken_links.append({"url": link_url, "status": status})

    if broken_links:
        details = [f"{b['url']} (HTTP {b['status']})" for b in broken_links[:3]]
        f = create_candidate_finding(
            title=f"Broken internal navigation links detected ({len(broken_links)} link(s))",
            category="navigation",
            severity="medium",
            url=broken_links[0]["url"],
            observation=f"Sampled internal links returned broken HTTP errors: {'; '.join(details)}.",
            method="http_redirect_aware_link_checker",
            source_skill="engagement-audit",
            action_summary="Fix or redirect broken internal destination URLs.",
            action_priority="medium",
            action_how_to_fix="Update broken link hrefs to their canonical working URLs or configure 301 redirects on the server.",
            fingerprint="engagement:broken-internal-links",
            status="confirmed",
            confidence="high",
            impact="medium"
        )
        findings.append(f.to_dict())

    return findings


SEARCH_AFFORDANCE_RE = re.compile(
    r'(?is)<input[^>]+type=["\']search["\']|role=["\']search["\']|'
    r'<input[^>]+name=["\'](?:q|s|query|search|keyword)["\']|'
    r'<form[^>]+(?:action|class|id)=["\'][^"\']*search'
)
ACCOUNT_AFFORDANCE_RE = re.compile(
    r"\b(sign in|signin|log in|login|my account|your account|dashboard|"
    r"sign out|log out|profile|saved items|wishlist|order history|"
    r"recently viewed|continue where you left off|recommended for you)\b",
    re.I
)


def evaluate_site_level_engagement(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """
    Engagement checks that are only meaningful across the whole site rather than per page.

    These target the specific arrival pattern this marketplace exists to diagnose: a visitor
    who lands mid-site from an AI citation, with no homepage context and no prior navigation.
    """
    findings = []
    pages = [
        (u, s) for u, s in inventory.pages.items()
        if not s.get("inconclusive") and s.get("status_code") == 200
    ]
    if not pages:
        return findings

    gt = inventory.ground_truth or {}
    brand = (gt.get("brand_name") or "").strip()
    brand_source = gt.get("brand_name_source", "unknown")
    origin = inventory.origin

    # 1. Cold-arrival orientation: does a deep page identify whose site it is?
    # Only run when the brand name was resolved confidently -- a domain-label guess is not a
    # solid enough basis to accuse a page of failing to name its own brand.
    if brand and len(brand) >= 3 and brand_source in ("organization_schema", "og_site_name", "short_title"):
        brand_tokens = [t for t in re.split(r"[^A-Za-z0-9]+", brand.lower()) if len(t) >= 3]
        anonymous = []
        for u, snap in pages:
            if not snap.get("is_deep_page"):
                continue
            haystack = f"{snap.get('title','')} {snap.get('visible_text','')}".lower()
            if brand_tokens and not any(tok in haystack for tok in brand_tokens):
                anonymous.append(u)
        if anonymous:
            f = create_candidate_finding(
                title="Deep pages never identify the brand, leaving cold arrivals unoriented",
                category="orientation",
                severity="medium",
                url=anonymous[0],
                observation=(
                    f"{len(anonymous)} deep page(s) contain no mention of \"{brand}\" in the title or "
                    f"body text (e.g. {', '.join(anonymous[:2])}). A visitor arriving here from an AI "
                    f"citation, with no homepage context, cannot tell whose site they are on -- and "
                    f"neither can an assistant attributing the quote."
                ),
                method="cold_arrival_brand_mention_check",
                source_skill="engagement-audit",
                action_summary="Name the brand in the header, title and footer of every page.",
                action_priority="medium",
                action_how_to_fix=(
                    "Include the brand name in the <title> of every page and in a persistent header "
                    "or footer, so a page that is the visitor's first contact still identifies its owner."
                ),
                fingerprint="engagement:deep-pages-anonymous",
                status="confirmed",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())

    # 2. Site search: the primary self-serve recovery path for a mid-site arrival.
    if not any(SEARCH_AFFORDANCE_RE.search(s.get("raw_html", "")) for _, s in pages):
        f = create_candidate_finding(
            title="No site search affordance found on any crawled page",
            category="navigation",
            severity="low",
            url=origin,
            observation=(
                f"None of the {len(pages)} crawled pages expose a search input, a search form or "
                f"role=\"search\". A visitor who arrives on the wrong page from an AI answer has no "
                f"way to find the right one without returning to the assistant."
            ),
            method="search_affordance_detection",
            source_skill="engagement-audit",
            action_summary="Add a site search box to the persistent header.",
            action_priority="low",
            action_how_to_fix=(
                "Add a search input in the global header and expose it with role=\"search\". Add "
                "WebSite JSON-LD with a potentialAction SearchAction so assistants can surface "
                "your search directly."
            ),
            fingerprint="engagement:no-site-search",
            status="likely-risk",
            confidence="medium",
            impact="low"
        )
        findings.append(f.to_dict())

    # 3. Personalization readiness (Appendix E): can the site use anything it knows about a
    # returning visitor? Reported as a readiness gap, never as a confirmed defect -- a static
    # crawl cannot observe personalization that only activates for a signed-in session.
    if not any(ACCOUNT_AFFORDANCE_RE.search(s.get("visible_text", "")) for _, s in pages):
        f = create_candidate_finding(
            title="No returning-visitor or account affordance detected",
            category="personalization-readiness",
            severity="low",
            url=origin,
            observation=(
                f"Across {len(pages)} crawled pages there is no sign-in, account, saved-items or "
                f"recently-viewed affordance in the visible text. Every visitor is therefore treated "
                f"as anonymous and first-time, so nothing the brand already knows about a returning "
                f"visitor can shape what they are shown."
            ),
            method="returning_visitor_affordance_detection",
            source_skill="engagement-audit",
            action_summary="Give returning visitors a way to be recognised, and use it.",
            action_priority="low",
            action_how_to_fix=(
                "Add an account or saved-state affordance appropriate to the site (sign-in, saved "
                "items, recently viewed, or a lightweight preference stored locally), then use it to "
                "surface relevant content on return rather than resetting every visitor to a cold start."
            ),
            fingerprint="engagement:no-personalization-readiness",
            status="proactive",
            confidence="medium",
            impact="low"
        )
        findings.append(f.to_dict())

    return findings


def evaluate_engagement_audit(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """Full engagement audit across all inventory pages."""
    all_findings = []
    for i, (url, snap) in enumerate(inventory.pages.items()):
        is_root = (i == 0 or url == inventory.seed_url or url == inventory.origin or url == inventory.origin + "/")
        page_findings = evaluate_page_engagement(snap, is_root=is_root)
        all_findings.extend(page_findings)

    # Site-level checks (cold-arrival orientation, search, personalization readiness)
    all_findings.extend(evaluate_site_level_engagement(inventory))

    # Check sample broken links
    broken_findings = check_broken_links_sample(inventory)
    all_findings.extend(broken_findings)
    return all_findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: engagement_scan.py <url_or_inventory_json> [--findings-only]"})); sys.exit(1)

    target = sys.argv[1]
    inventory = get_or_crawl_inventory(target)
    findings = evaluate_engagement_audit(inventory)

    if "--findings-only" in sys.argv:
        print(json.dumps(findings, indent=2))
    else:
        out = {
            "site": inventory.origin,
            "pages_audited": len(inventory.pages),
            "findings": findings
        }
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
