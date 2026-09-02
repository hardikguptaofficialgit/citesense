#!/usr/bin/env python3
"""
fix_snippets.py -- Generates ready-to-paste JSON-LD fix snippets for structured-data findings.

A snippet is only produced when the audit already holds enough *real* observed data
(SiteInventory ground_truth + cached page snapshots + the finding's own evidence_details)
to populate the entity's identifying fields. Fields with no known value are emitted as
clearly marked "REPLACE_WITH_..." placeholders, and a snippet that would be mostly
placeholders is suppressed entirely rather than presented as a fix.

Nothing here invents facts: every non-placeholder value is copied verbatim from data the
crawl actually observed.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

PLACEHOLDER_PREFIX = "REPLACE_WITH_"

# Schema.org types we know how to pre-populate from observed audit data.
SUPPORTED_TYPES = ("Organization", "Product", "FAQPage", "Article", "BreadcrumbList")

# A finding must express *absence* of markup before we offer to add it. This keeps
# snippets off findings like "malformed JSON-LD" where the fix is repair, not insertion.
ABSENCE_TOKENS = ("missing", "lacks", "absent", "no schema", "not present", "omit")

# Ordered so that more specific types win: a "Product and Offer" finding is a Product fix.
TYPE_KEYWORDS = (
    ("BreadcrumbList", ("breadcrumb",)),
    ("FAQPage", ("faqpage", "faq page", "frequently asked")),
    ("Product", ("product", "offer", "pricing schema")),
    ("Article", ("article", "newsarticle", "blogposting")),
    ("Organization", ("organization", "localbusiness", "corporation")),
)


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX)


def _count_values(node: Any) -> Tuple[int, int]:
    """Counts (real, placeholder) data leaves, ignoring @context/@type structural keys."""
    real = placeholder = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.startswith("@"):
                continue
            r, p = _count_values(v)
            real += r
            placeholder += p
    elif isinstance(node, list):
        for item in node:
            r, p = _count_values(item)
            real += r
            placeholder += p
    elif isinstance(node, str):
        if _is_placeholder(node):
            placeholder += 1
        elif node.strip():
            real += 1
    elif node is not None:
        real += 1
    return real, placeholder


def snippet_type_for_finding(finding: Dict[str, Any]) -> Optional[str]:
    """Returns the Schema.org type a finding is asking for, or None if it does not qualify."""
    if finding.get("category") != "structured-data":
        return None
    haystack = " ".join(
        str(finding.get(k, "")) for k in ("title", "fingerprint", "suggested_action")
    ).lower()
    if not any(tok in haystack for tok in ABSENCE_TOKENS):
        return None
    for type_name, keywords in TYPE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return type_name
    return None


def finding_url(finding: Dict[str, Any], fallback: str = "") -> str:
    """Recovers the URL a finding was observed at, from evidence_details or evidence text."""
    details = finding.get("evidence_details") or {}
    if isinstance(details, dict) and details.get("url"):
        return str(details["url"])
    m = re.search(r"https?://[^\s,)\"'<>]+", str(finding.get("evidence", "")))
    if m:
        return m.group(0).rstrip(".")
    return fallback


def _lookup_page(pages: Optional[Dict[str, Any]], url: str) -> Dict[str, Any]:
    """Finds the cached page snapshot for a URL, tolerating trailing-slash/final_url drift."""
    if not pages or not url:
        return {}
    if url in pages:
        return pages[url] or {}
    target_path = urlparse(url).path.rstrip("/")
    for key, snap in pages.items():
        if not isinstance(snap, dict):
            continue
        candidates = {c for c in (key, snap.get("url", ""), snap.get("final_url", "")) if c}
        if url.rstrip("/") in {c.rstrip("/") for c in candidates}:
            return snap
        if target_path and urlparse(key).path.rstrip("/") == target_path:
            return snap
    return {}


def _entity_name(snapshot: Dict[str, Any]) -> str:
    """Best observed human name for the page subject: H1 first, then the title lead segment."""
    for h1 in snapshot.get("h1_texts") or []:
        if h1 and h1.strip():
            return h1.strip()
    title = (snapshot.get("title") or "").strip()
    if title:
        return re.split(r"\s+[|–—-]\s+", title)[0].strip() or title
    return ""


def _observed_publish_date(snapshot: Dict[str, Any]) -> str:
    dates = snapshot.get("dates_and_claims") or {}
    for key in ("meta_modified_time", "visible_last_updated"):
        if dates.get(key):
            return str(dates[key])
    jsonld_dates = dates.get("jsonld_dates") or {}
    if isinstance(jsonld_dates, dict):
        for key in ("datePublished", "dateModified"):
            if jsonld_dates.get(key):
                return str(jsonld_dates[key])
    return ""


def _build_organization(gt, site_url, snapshot):
    key_facts = gt.get("key_facts") or {}
    name = (gt.get("brand_name") or "").strip()
    node = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name or PLACEHOLDER_PREFIX + "YOUR_ORGANIZATION_NAME",
        "url": site_url or PLACEHOLDER_PREFIX + "YOUR_HOMEPAGE_URL",
        "logo": PLACEHOLDER_PREFIX + "YOUR_LOGO_URL",
    }
    description = key_facts.get("description") or snapshot.get("meta_description") or ""
    if description:
        node["description"] = description
    if key_facts.get("founding_year"):
        node["foundingDate"] = str(key_facts["founding_year"])
    if key_facts.get("phone"):
        node["telephone"] = str(key_facts["phone"])
    if key_facts.get("email"):
        node["email"] = str(key_facts["email"])
    same_as = gt.get("same_as") or []
    node["sameAs"] = list(same_as) if same_as else [PLACEHOLDER_PREFIX + "YOUR_WIKIPEDIA_OR_LINKEDIN_URL"]

    identity_ok = bool(name) and bool(site_url)
    # Name + URL alone is a bare template; require at least one further observed fact.
    extras = bool(same_as) or any(
        k in node for k in ("description", "foundingDate", "telephone", "email")
    )
    return node, identity_ok and extras


def _build_product(gt, page_url, snapshot):
    name = _entity_name(snapshot)
    node = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name or PLACEHOLDER_PREFIX + "PRODUCT_NAME",
        "url": page_url or PLACEHOLDER_PREFIX + "PRODUCT_PAGE_URL",
    }
    if gt.get("brand_name"):
        node["brand"] = {"@type": "Brand", "name": gt["brand_name"]}
    if snapshot.get("meta_description"):
        node["description"] = snapshot["meta_description"]
    node["offers"] = {
        "@type": "Offer",
        "url": page_url or PLACEHOLDER_PREFIX + "PRODUCT_PAGE_URL",
        "price": PLACEHOLDER_PREFIX + "PRICE_AMOUNT",
        "priceCurrency": PLACEHOLDER_PREFIX + "ISO_4217_CURRENCY_CODE",
    }
    return node, bool(name) and bool(page_url)


def _build_article(gt, page_url, snapshot):
    headline = _entity_name(snapshot)
    node = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline or PLACEHOLDER_PREFIX + "ARTICLE_HEADLINE",
        "url": page_url or PLACEHOLDER_PREFIX + "ARTICLE_URL",
    }
    published = _observed_publish_date(snapshot)
    node["datePublished"] = published or PLACEHOLDER_PREFIX + "ISO_8601_PUBLISH_DATE"
    node["author"] = {"@type": "Person", "name": PLACEHOLDER_PREFIX + "AUTHOR_NAME"}
    if gt.get("brand_name"):
        node["publisher"] = {"@type": "Organization", "name": gt["brand_name"]}
    return node, bool(headline) and bool(page_url)


def _build_faqpage(gt, page_url, snapshot):
    # Questions are lifted verbatim from headings the crawl actually saw on the page.
    questions = []
    for h in snapshot.get("headings") or []:
        text = (h.get("text") or "").strip()
        if text.endswith("?") and text not in questions:
            questions.append(text)
    main_entity = [
        {
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": PLACEHOLDER_PREFIX + "ANSWER_TEXT_AS_PUBLISHED_ON_PAGE",
            },
        }
        for q in questions[:10]
    ]
    node = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "url": page_url or PLACEHOLDER_PREFIX + "FAQ_PAGE_URL",
        "mainEntity": main_entity,
    }
    return node, bool(main_entity) and bool(page_url)


def _humanize_segment(segment: str) -> str:
    cleaned = re.sub(r"\.(html?|php|aspx)$", "", segment)
    return re.sub(r"[-_]+", " ", cleaned).strip().title()


def _build_breadcrumblist(gt, page_url, snapshot):
    parsed = urlparse(page_url)
    origin = "{0}://{1}".format(parsed.scheme, parsed.netloc) if parsed.netloc else ""
    segments = [s for s in parsed.path.split("/") if s]
    items = []
    if origin:
        items.append({
            "@type": "ListItem",
            "position": 1,
            "name": gt.get("brand_name") or "Home",
            "item": origin + "/",
        })
    leaf_name = _entity_name(snapshot)
    accumulated = origin
    for i, seg in enumerate(segments, start=2):
        accumulated = urljoin(accumulated + "/", seg)
        is_leaf = (i == len(segments) + 1)
        items.append({
            "@type": "ListItem",
            "position": i,
            "name": leaf_name if (is_leaf and leaf_name) else _humanize_segment(seg),
            "item": accumulated,
        })
    node = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }
    return node, len(items) >= 2


_BUILDERS = {
    "Organization": _build_organization,
    "Product": _build_product,
    "Article": _build_article,
    "FAQPage": _build_faqpage,
    "BreadcrumbList": _build_breadcrumblist,
}


def render_snippet(jsonld: Dict[str, Any]) -> str:
    """Wraps a JSON-LD object in a paste-ready <script> block."""
    body = json.dumps(jsonld, indent=2, ensure_ascii=False)
    return '<script type="application/ld+json">\n' + body + "\n</script>"


def generate_fix_snippet(
    finding: Dict[str, Any],
    ground_truth: Optional[Dict[str, Any]] = None,
    pages: Optional[Dict[str, Any]] = None,
    site_url: str = "",
) -> Optional[str]:
    """
    Returns a ready-to-paste JSON-LD <script> block for a qualifying structured-data
    finding, or None when the audit lacks enough observed data to populate it honestly.

    Emission requires BOTH:
      1. every identifying field for the type carries an observed value, and
      2. real values >= placeholder values across the snippet.
    """
    type_name = snippet_type_for_finding(finding)
    if not type_name:
        return None

    gt = ground_truth or {}
    url = finding_url(finding, fallback=site_url)
    snapshot = _lookup_page(pages, url)

    if type_name == "Organization":
        target = site_url or gt.get("url") or url
        node, identity_ok = _build_organization(gt, target, snapshot)
    else:
        node, identity_ok = _BUILDERS[type_name](gt, url, snapshot)

    if not identity_ok:
        return None

    real, placeholder = _count_values(node)
    if real < placeholder:
        return None

    return render_snippet(node)


def explain_fix_snippet(
    finding: Dict[str, Any],
    ground_truth: Optional[Dict[str, Any]] = None,
    pages: Optional[Dict[str, Any]] = None,
    site_url: str = "",
) -> Dict[str, Any]:
    """
    Same decision as generate_fix_snippet, but reports *why* a snippet was or was not
    emitted. Used by the CLI so a suppressed snippet is visibly a deliberate refusal to
    guess, not a silent failure.
    """
    type_name = snippet_type_for_finding(finding)
    result = {
        "id": finding.get("id"),
        "title": finding.get("title"),
        "schema_type": type_name,
        "emitted": False,
        "reason": "",
        "snippet": None,
    }
    if not type_name:
        result["reason"] = "not a structured-data finding requesting a supported schema type"
        return result

    gt = ground_truth or {}
    url = finding_url(finding, fallback=site_url)
    snapshot = _lookup_page(pages, url)

    if type_name == "Organization":
        node, identity_ok = _build_organization(gt, site_url or gt.get("url") or url, snapshot)
    else:
        node, identity_ok = _BUILDERS[type_name](gt, url, snapshot)

    if not identity_ok:
        if not gt:
            result["reason"] = (
                "no ground_truth supplied -- pass --inventory (a saved SiteInventory from "
                "run_audit.py --save-inventory), since report.json alone carries no ground truth"
            )
        elif type_name in ("Product", "Article") and not snapshot:
            result["reason"] = (
                "no cached page snapshot for {0}; refusing to invent a {1} name".format(
                    url or "(unknown url)", type_name
                )
            )
        else:
            result["reason"] = (
                "insufficient observed data to fill the identifying fields for {0}".format(type_name)
            )
        return result

    real, placeholder = _count_values(node)
    if real < placeholder:
        result["reason"] = (
            "suppressed: {0} placeholder values vs {1} real -- would be a template, not a fix".format(
                placeholder, real
            )
        )
        return result

    result["emitted"] = True
    result["reason"] = "{0} real values, {1} marked placeholder".format(real, placeholder)
    result["snippet"] = render_snippet(node)
    return result


def attach_fix_snippets(
    findings: List[Dict[str, Any]],
    ground_truth: Optional[Dict[str, Any]] = None,
    pages: Optional[Dict[str, Any]] = None,
    site_url: str = "",
) -> int:
    """
    Adds suggested_action['fix_snippet'] in place for every qualifying finding.
    Returns the number of snippets attached. Findings that do not qualify are untouched.
    """
    attached = 0
    for f in findings:
        action = f.get("suggested_action")
        if not isinstance(action, dict) or action.get("fix_snippet"):
            continue
        snippet = generate_fix_snippet(
            f, ground_truth=ground_truth, pages=pages, site_url=site_url
        )
        if snippet:
            action["fix_snippet"] = snippet
            attached += 1
    return attached


def _main(argv=None):
    """
    CLI: inspect (and optionally write) the fix snippets for an existing report.

        python fix_snippets.py report.json [--inventory inventory.json] [--output annotated.json]

    Without --inventory nothing is emitted: report.json carries no ground_truth, and this
    tool will not fabricate one. The per-finding `reason` says exactly that.
    """
    import argparse
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from report_io import ReportIOError, fail, load_report, write_text

    parser = argparse.ArgumentParser(
        description="Generate JSON-LD fix snippets for a report's structured-data findings."
    )
    parser.add_argument("report", help="Path to a report.json file")
    parser.add_argument(
        "--inventory",
        help="Saved SiteInventory JSON (run_audit.py --save-inventory) or a bare "
             "ground_truth JSON object. Without it, no snippet can be populated.",
    )
    parser.add_argument("--output", help="Write the report back out with snippets attached")
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
        ground_truth, pages = None, None
        if args.inventory:
            data = load_report(args.inventory, label="inventory")
            if "ground_truth" in data or "pages" in data:
                ground_truth, pages = data.get("ground_truth"), data.get("pages")
            else:
                ground_truth = data

        site_url = report.get("site") or ""
        findings = report.get("findings") or []
        results = [
            explain_fix_snippet(f, ground_truth=ground_truth, pages=pages, site_url=site_url)
            for f in findings
        ]
        candidates = [r for r in results if r["schema_type"]]
        attached = attach_fix_snippets(
            findings, ground_truth=ground_truth, pages=pages, site_url=site_url
        )
        if args.output:
            write_text(args.output, json.dumps(report, indent=2))
    except ReportIOError as exc:
        return fail(exc)

    print(json.dumps({
        "site": site_url,
        "findings_examined": len(findings),
        "snippet_candidates": len(candidates),
        "snippets_emitted": attached,
        "ground_truth_supplied": bool(ground_truth),
        "output": args.output,
        "candidates": [
            {k: v for k, v in r.items() if k != "snippet"} for r in candidates
        ],
    }, indent=2))
    for r in candidates:
        if r["snippet"]:
            print("\n--- {0} ({1}) ---\n{2}".format(r["id"], r["schema_type"], r["snippet"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
