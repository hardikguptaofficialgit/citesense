#!/usr/bin/env python3
"""
freshness_and_consistency_scan.py -- Evaluates internal temporal freshness and cross-page consistency.
Claim-based freshness: detects actual stale or conflicting claims instead of treating missing dateModified as a defect.
Emits structured CandidateFindings.
"""
import os
import sys
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from audit_common import safe_fetch, visible_text
from models import create_candidate_finding, CandidateFinding
from site_inventory import SiteInventory, get_or_crawl_inventory

CURRENT_YEAR = datetime.now(timezone.utc).year


def evaluate_freshness_and_consistency(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """Evaluates cross-page consistency and claim-based freshness across SiteInventory pages."""
    findings = []
    pages = inventory.pages

    # 1. Cross-page consistency checks (Founding year, phone numbers, addresses)
    founding_by_page = {}
    phone_by_page = {}
    stale_claims_by_page = {}

    for url, snap in pages.items():
        if snap.get("inconclusive") or snap.get("status_code") != 200:
            continue
        dates_info = snap.get("dates_and_claims", {})
        
        # Founding years
        f_years = dates_info.get("founding_years", [])
        if f_years:
            founding_by_page[url] = set(str(y) for y in f_years)

        # Phone numbers
        phones = dates_info.get("phones", [])
        if phones:
            phone_by_page[url] = set(phones)

        # Stale dated claims (e.g. promotions, pricing, webinars from >= 2 years ago)
        stale_claims = dates_info.get("stale_dated_claims", [])
        if stale_claims:
            stale_claims_by_page[url] = stale_claims

    # Check for founding year mismatch
    all_founding_years = set()
    for yrs in founding_by_page.values():
        all_founding_years |= yrs

    if len(all_founding_years) > 1:
        details = []
        for u, yrs in founding_by_page.items():
            details.append(f"{u}: {', '.join(sorted(yrs))}")
        f = create_candidate_finding(
            title=f"Inconsistent founding year claimed across site pages ({', '.join(sorted(all_founding_years))})",
            category="internal-consistency",
            severity="high",
            url=list(founding_by_page.keys())[0],
            observation=f"Different pages state contradictory founding years: {'; '.join(details)}.",
            method="cross_page_fact_comparison",
            source_skill="freshness-corroboration",
            action_summary="Unify the company founding year across all web pages and structured data.",
            action_priority="high",
            action_how_to_fix="Identify the authoritative founding date and update all occurrences on the homepage, About page, footer, and Organization JSON-LD.",
            fingerprint="consistency:founding-year-mismatch",
            status="confirmed",
            confidence="high",
            impact="high"
        )
        findings.append(f.to_dict())

    # Check for phone number normalization mismatch (ignoring formatting differences)
    def norm_phone(p: str) -> str:
        return re.sub(r"\D", "", p)

    normalized_phone_groups = {}
    for u, phs in phone_by_page.items():
        for p in phs:
            norm = norm_phone(p)
            if len(norm) >= 7:  # Valid phone length
                normalized_phone_groups.setdefault(norm, set()).add((u, p))

    if len(normalized_phone_groups) > 1:
        distinct_numbers = list(normalized_phone_groups.keys())
        if len(distinct_numbers) > 1:
            details = [f"Number {k}: found on {len(v)} page(s)" for k, v in normalized_phone_groups.items()]
            f = create_candidate_finding(
                title="Conflicting primary contact phone numbers published across site",
                category="internal-consistency",
                severity="medium",
                url=list(phone_by_page.keys())[0],
                observation=f"Multiple distinct phone numbers are published across different pages without branch context: {'; '.join(details)}.",
                method="cross_page_contact_comparison",
                source_skill="freshness-corroboration",
                action_summary="Standardize customer service and contact phone numbers.",
                action_priority="medium",
                action_how_to_fix="Ensure primary contact numbers are consistent across headers, footers, and Contact pages, with clear labels for departmental lines.",
                fingerprint="consistency:phone-number-mismatch",
                status="likely-risk",
                confidence="medium",
                impact="medium"
            )
            findings.append(f.to_dict())

    # 2. Claim-based Freshness (Actual expired promotions / stale dated claims)
    for url, stale_claims in stale_claims_by_page.items():
        # Pick top 2 most prominent stale claims
        for claim in stale_claims[:2]:
            year = claim.get("year")
            age = claim.get("age_years", 0)
            context = claim.get("context", "")
            if age >= 2 and any(k in context.lower() for k in ("price", "pricing", "current", "event", "webinar", "sale", "discount", "promo", "roadmap")):
                f = create_candidate_finding(
                    title=f"Outdated time-sensitive claim or promotion found on active page ({year})",
                    category="freshness",
                    severity="medium",
                    url=url,
                    observation=f"Page contains active time-sensitive statement referencing {year} ({age} years old): \"{context}\".",
                    method="dated_claim_temporal_analysis",
                    source_skill="freshness-corroboration",
                    action_summary="Update or archive expired time-sensitive offers and claims.",
                    action_priority="medium",
                    action_how_to_fix=f"Review the text referencing {year} on {url} and update with current pricing/event information or remove expired promotions.",
                    fingerprint=f"freshness:stale-claim:{year}:{url}",
                    status="confirmed",
                    confidence="high",
                    impact="medium"
                )
                findings.append(f.to_dict())

    # 3. Severely outdated copyright notice -- one site-wide finding, not one per page.
    # The footer is template-level, so N crawled pages previously yielded N identical findings.
    stale_copyright_pages = []
    for url, snap in pages.items():
        if snap.get("inconclusive") or snap.get("status_code") != 200:
            continue
        newest_copy = snap.get("dates_and_claims", {}).get("newest_copyright_year")
        if newest_copy and (CURRENT_YEAR - newest_copy >= 3):
            stale_copyright_pages.append((url, newest_copy))

    if stale_copyright_pages:
        oldest_year = min(y for _, y in stale_copyright_pages)
        page_list = ", ".join(u for u, _ in stale_copyright_pages[:3])
        more = f" (+{len(stale_copyright_pages) - 3} more)" if len(stale_copyright_pages) > 3 else ""
        f = create_candidate_finding(
            title=f"Stale copyright notice ({oldest_year}) in site footer template",
            category="freshness",
            severity="low",
            url=stale_copyright_pages[0][0],
            observation=(
                f"Footer copyright notice resolves to {oldest_year} "
                f"(gap of {CURRENT_YEAR - oldest_year} years) on {len(stale_copyright_pages)} crawled page(s): "
                f"{page_list}{more}. Year ranges such as '2005-{CURRENT_YEAR}' are read as current and not flagged."
            ),
            method="copyright_year_detector",
            source_skill="freshness-corroboration",
            action_summary="Update the site footer copyright year.",
            action_priority="low",
            action_how_to_fix=(
                f"Update the footer copyright notice to {CURRENT_YEAR}, or render the year dynamically "
                f"server-side so it never goes stale."
            ),
            fingerprint="freshness:stale-copyright",
            status="confirmed",
            confidence="high",
            impact="low"
        )
        findings.append(f.to_dict())

    return findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: freshness_and_consistency_scan.py <url_or_inventory_json> [url2 ...] [--findings-only]"})); sys.exit(1)

    target = sys.argv[1]
    if target.endswith(".json") and os.path.exists(target):
        inventory = SiteInventory.load_json(target)
    else:
        inventory = SiteInventory(target)
        urls = [arg for arg in sys.argv[1:] if arg.startswith("http")]
        if len(urls) > 1:
            inventory.crawl_site(max_pages=len(urls), additional_paths=[re.sub(r"^https?://[^/]+", "", u) for u in urls])
        else:
            inventory.crawl_site(max_pages=5)

    findings = evaluate_freshness_and_consistency(inventory)

    if "--findings-only" in sys.argv:
        print(json.dumps(findings, indent=2))
    else:
        out = {
            "current_year_reference": CURRENT_YEAR,
            "pages_analyzed": len(inventory.pages),
            "findings": findings
        }
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
