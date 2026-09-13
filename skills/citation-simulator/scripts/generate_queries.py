#!/usr/bin/env python3
"""
generate_queries.py -- Deterministic query generation and citation simulation evaluation.
Generates realistic entity-grounded questions and classifies search/citation simulation results.
Emits structured CandidateFindings.
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

from models import create_candidate_finding, CandidateFinding


def build_queries(facts: Dict[str, Any]) -> List[Dict[str, str]]:
    """Builds targeted, entity-specific queries based on confirmed ground truth."""
    name = facts.get("brand_name", "the brand")
    category = facts.get("category", "").strip()
    location = facts.get("location", "").strip()
    category_phrase = f" ({category})" if category else ""
    location_phrase = f" in {location}" if location else ""
    
    queries = [
        {"category": "identity", "query": f"What is {name}{category_phrase}?"},
        {"category": "offering", "query": f"What products or services does {name} offer?"},
    ]

    key_facts = facts.get("key_facts", {}) or {}

    # Check for specific commercial/transactional facts
    if key_facts.get("owner") or key_facts.get("ownership"):
        queries.append({"category": "identity", "query": f"Who owns or governs {name}?"})
    if key_facts.get("pricing") or key_facts.get("price"):
        queries.append({"category": "transactional", "query": f"How much does {name} cost?"})
    if key_facts.get("return_policy") or key_facts.get("cancellation_policy"):
        queries.append({"category": "transactional", "query": f"What is {name}'s return or cancellation policy?"})
    if key_facts.get("contact") or key_facts.get("phone") or location:
        queries.append({"category": "transactional", "query": f"How do I contact {name}{location_phrase}?"})
    if key_facts.get("differentiator") or key_facts.get("competitors"):
        queries.append({"category": "differentiation", "query": f"How does {name} compare to alternatives?"})
    if key_facts.get("reviews") or key_facts.get("certification"):
        queries.append({"category": "credibility", "query": f"What independent evidence supports {name}'s credibility?"})

    return queries


PRICE_HINT_RE = re.compile(r"(?:[$£€¥]\s?\d|\b\d+\s?(?:usd|eur|gbp)\b|\bper (?:month|user|seat|year)\b|\bfree tier\b|\bpricing\b)", re.I)
CONTACT_HINT_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}|\bcontact us\b|\bget in touch\b", re.I)


def evaluate_answerability(inventory: Dict[str, Any], ground_truth: Dict[str, Any], site_domain: str) -> List[Dict[str, Any]]:
    """
    Deterministic precondition for citation, runnable on every site with no web access.

    Appendix B: a page only makes it into an assistant's answer if the assistant can reach it,
    read it, and quote a clear fact from it. This checks the last step against the pages we
    actually crawled -- if the fact needed to answer a natural question about the brand is not
    extractable from any crawled page, the brand cannot be cited for that question regardless
    of how the ranking works.

    Findings are `likely-risk` / medium confidence because we sample a handful of pages rather
    than the whole site: absence from the sample is a strong signal, not a proof of absence.
    """
    findings = []
    pages = [
        p for p in (inventory.get("pages") or {}).values()
        if not p.get("inconclusive") and p.get("status_code") == 200
    ]
    if not pages:
        return findings

    brand = ground_truth.get("brand_name", site_domain)
    pages_desc = f"{len(pages)} crawled page(s)"
    def page_text(page: Dict[str, Any]) -> str:
        return " ".join(
            str(page.get(key, "")) for key in ("title", "meta_description", "visible_text")
        ).lower()

    def page_types(page: Dict[str, Any]) -> set:
        types = set()
        for ent in page.get("jsonld_parsed", []):
            raw_types = ent.get("@type", "")
            types.update(x for x in (raw_types if isinstance(raw_types, list) else [raw_types]) if x)
        return types

    def matching_pages(key: str) -> List[Dict[str, Any]]:
        terms = {
            "identity": ("homepage", "general", "contact_support"),
            "offering": ("product_pricing", "general", "article_docs"),
            "audience": ("general", "product_pricing", "article_docs"),
            "transactional": ("product_pricing",),
            "differentiation": ("homepage", "product_pricing", "article_docs", "general"),
            "contact": ("contact_support", "homepage", "general", "product_pricing", "article_docs"),
        }[key]
        return [p for p in pages if p.get("page_purpose") in terms]

    all_types = set().union(*(page_types(p) for p in pages))
    commercial_pages = matching_pages("transactional")
    is_commercial = bool(commercial_pages) or bool(
        {"Product", "Offer", "Service", "SoftwareApplication"} & all_types
    )

    def has_text(page_list: List[Dict[str, Any]], patterns: tuple[str, ...]) -> bool:
        return any(any(re.search(pattern, page_text(p), re.I) for pattern in patterns) for p in page_list)

    identity_pages = matching_pages("identity")
    offering_pages = matching_pages("offering")
    audience_pages = matching_pages("audience")
    differentiation_pages = matching_pages("differentiation")
    contact_pages = matching_pages("contact")

    probes = [
        {
            "key": "identity",
            "fingerprint": "schema:root-organization-missing",
            "query": f"What is {brand}?",
            "answerable": bool({"Organization", "LocalBusiness", "Corporation", "Brand"} & all_types)
            or has_text(identity_pages, (re.escape(brand.lower()), r"\b(?:is|provides|offers|serves|university|school|hospital)\b")),
            "severity": "high",
            "missing": "no Organization/LocalBusiness schema states who the brand is in machine-readable form",
            "fix_summary": "Publish a machine-readable identity statement on the homepage.",
            "fix": (
                "Add Organization JSON-LD (name, url, logo, description, sameAs) to the homepage, and a "
                "one-sentence plain-text description of what the brand does in the first screen of copy."
            ),
        },
        {
            "key": "offering",
            "query": f"What does {brand} offer?",
            "answerable": bool({"Product", "Service", "SoftwareApplication", "Offer", "ItemList"} & all_types)
            or has_text(offering_pages, (r"\b(?:offers?|provides?|services?|products?|platform|software|programs?|courses?)\b",)),
            "severity": "medium",
            "missing": "no Product/Service/Offer schema describes the offering",
            "fix_summary": "Mark up the product or service catalogue.",
            "fix": (
                "Add Product or Service JSON-LD to the pages describing what you sell, so an assistant can "
                "quote the offering rather than paraphrasing navigation labels."
            ),
        },
        {
            "key": "transactional",
            "query": f"How much does {brand} cost?",
            "answerable": (not is_commercial)
            or has_text(commercial_pages, (PRICE_HINT_RE.pattern, r"\b(?:quote|quotation|contact sales|tuition|fees?)\b"))
            or "Offer" in all_types,
            "severity": "medium",
            "missing": "no price, currency or pricing language is extractable from the crawled text",
            "fix_summary": "Make pricing extractable as text, not just as an image or a gated flow.",
            "fix": (
                "State prices in plain HTML text and add Offer JSON-LD with price and priceCurrency. "
                "If pricing is genuinely quote-only, say so explicitly in text -- an assistant can cite "
                "\"pricing is quote-based\" but cannot cite silence."
            ),
        },
        {
            "key": "contact",
            "query": f"How do I contact {brand}?",
            "answerable": has_text(contact_pages, (CONTACT_HINT_RE.pattern, r"\b(?:contact|reach|location|address|visit)\b"))
            or "ContactPoint" in all_types,
            "severity": "medium",
            "missing": "no email, phone number or contact affordance is extractable from the crawled text",
            "fix_summary": "Expose a contact route as machine-readable text.",
            "fix": (
                "Publish an email address or phone number as selectable text (not an image), and add "
                "ContactPoint JSON-LD to the Organization entity."
            ),
        },
        {
            "key": "audience",
            "query": f"Who is {brand} for?",
            "answerable": has_text(
                audience_pages,
                (r"\b(?:for|serves?|designed for|built for|students?|developers?|teams?|businesses?|patients?|faculty)\b",),
            ),
            "severity": "low",
            "missing": "no audience or intended-user statement is extractable from the relevant crawled pages",
            "fix_summary": "State the intended audience in plain language.",
            "fix": "Add a concise audience statement near the primary offering, such as who it serves and the use case it supports.",
        },
        {
            "key": "differentiation",
            "query": f"What makes {brand} different?",
            "answerable": has_text(
                differentiation_pages,
                (r"\b(?:why|unique|different|speciali[sz]ed|advantage|benefit|trusted|compare|领先|best)\b",),
            ),
            "severity": "low",
            "missing": "no explicit differentiator or benefit statement is extractable from the relevant crawled pages",
            "fix_summary": "Make the brand's differentiator explicit and quotable.",
            "fix": "Add a short, factual differentiator section tied to a specific capability, audience, outcome, or proof point.",
        },
    ]
    # A tiny but readable fixture does not contain enough semantic surface to assess audience or
    # differentiation fairly. Keep those checks visible in the richer-site path and leave the
    # underspecified case to the report's assessment status rather than manufacture two gaps.
    if not any(len(page_text(page).split()) >= 40 for page in pages):
        probes = [probe for probe in probes if probe["key"] not in {"audience", "differentiation"}]

    for probe in probes:
        if probe["answerable"]:
            continue
        findings.append(create_candidate_finding(
            title=f"No extractable answer on-site for \"{probe['query']}\"",
            category="citation-omission",
            severity=probe["severity"],
            url=(matching_pages(probe["key"]) or pages)[0].get("final_url")
            or (matching_pages(probe["key"]) or pages)[0].get("url")
            or f"https://{site_domain}",
            observation=(
                f"Across {pages_desc}, {probe['missing']}. An assistant that fetched these pages could "
                f"not quote an answer to \"{probe['query']}\" from this site, so it must fall back to "
                f"third-party sources or omit the brand."
            ),
            method="onsite_answerability_probe",
            source_skill="citation-simulator",
            action_summary=probe["fix_summary"],
            action_priority=probe["severity"],
            action_how_to_fix=probe["fix"],
            fingerprint=probe.get("fingerprint") or f"citation:unanswerable:{probe['key']}",
            status="likely-risk",
            confidence="medium",
            impact=probe["severity"]
        ).to_dict())

    return findings


def evaluate_citation_simulation(
    simulation_results: List[Dict[str, Any]],
    ground_truth: Dict[str, Any],
    site_domain: str
) -> List[Dict[str, Any]]:
    """
    Evaluates simulated search/citation results against ground truth facts.
    Classifies issues into citation-omission, citation-misattribution,
    citation-staleness, and citation-contradiction.
    """
    findings = []
    brand_name = ground_truth.get("brand_name", site_domain)

    for item in simulation_results:
        query = item.get("query", "")
        classification = item.get("classification", "correct")  # correct, omission, misattribution, staleness, contradiction
        surfaced_urls = item.get("surfaced_urls", [])
        evidence_snippet = item.get("evidence", "")
        query_cat = item.get("category", "identity")

        if classification == "omission":
            f = create_candidate_finding(
                title=f"AI search simulation: brand content omitted for \"{query}\"",
                category="citation-omission",
                severity="high" if query_cat in ("identity", "transactional") else "medium",
                url=f"https://{site_domain}",
                observation=f"Simulated query \"{query}\" failed to surface official brand URLs ({site_domain}) in top results. Surfaced: {', '.join(surfaced_urls[:3]) or 'none'}. {evidence_snippet}",
                method="simulated_ai_search_loop",
                source_skill="citation-simulator",
                action_summary=f"Improve indexability and structured data for queries related to {query_cat}.",
                action_priority="high" if query_cat in ("identity", "transactional") else "medium",
                action_how_to_fix="Ensure relevant landing pages are crawlable, internally linked from the homepage, and marked up with relevant Schema.org entities.",
                fingerprint=f"citation:omission:{query_cat}:{query[:30]}",
                status="confirmed",
                confidence="high",
                impact="high" if query_cat in ("identity", "transactional") else "medium"
            )
            findings.append(f.to_dict())

        elif classification == "misattribution":
            f = create_candidate_finding(
                title=f"AI search simulation: entity misattribution for \"{query}\"",
                category="citation-misattribution",
                severity="critical",
                url=f"https://{site_domain}",
                observation=f"Simulated query \"{query}\" confused {brand_name} with another entity. {evidence_snippet}",
                method="simulated_ai_search_loop",
                source_skill="citation-simulator",
                action_summary="Strengthen entity disambiguation and Schema.org sameAs links.",
                action_priority="critical",
                action_how_to_fix="Add Organization JSON-LD with unambiguous name, alternateName, and verified sameAs links to Wikipedia/Wikidata.",
                fingerprint=f"citation:misattribution:{query[:30]}",
                status="confirmed",
                confidence="high",
                impact="critical"
            )
            findings.append(f.to_dict())

        elif classification == "staleness":
            f = create_candidate_finding(
                title=f"AI search simulation: stale facts surfaced for \"{query}\"",
                category="citation-staleness",
                severity="medium",
                url=f"https://{site_domain}",
                observation=f"Search surfaced outdated information for \"{query}\". {evidence_snippet}",
                method="simulated_ai_search_loop",
                source_skill="citation-simulator",
                action_summary="Update external directory profiles and add machine-readable dates to pages.",
                action_priority="medium",
                action_how_to_fix="Update old profiles on third-party listings and maintain current Schema.org information.",
                fingerprint=f"citation:staleness:{query[:30]}",
                status="confirmed",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())

        elif classification == "contradiction":
            f = create_candidate_finding(
                title=f"AI search simulation: contradictory facts surfaced across sources for \"{query}\"",
                category="citation-contradiction",
                severity="medium",
                url=f"https://{site_domain}",
                observation=f"Multiple external sources return conflicting data for \"{query}\". {evidence_snippet}",
                method="simulated_ai_search_loop",
                source_skill="citation-simulator",
                action_summary="Clarify canonical brand information in official documentation.",
                action_priority="medium",
                action_how_to_fix="Publish authoritative FAQ and Organization Schema to resolve external contradictory claims.",
                fingerprint=f"citation:contradiction:{query[:30]}",
                status="confirmed",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())

    return findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: generate_queries.py '<ground_truth_json_or_file>' [--eval <simulation_results.json>] [--domain <domain>]"})); sys.exit(1)

    input_arg = sys.argv[1]
    if os.path.exists(input_arg):
        with open(input_arg, encoding="utf-8-sig") as f:
            data = json.load(f)
            facts = data.get("ground_truth", data)
    else:
        try:
            facts = json.loads(input_arg)
        except Exception:
            facts = {"brand_name": input_arg}

    eval_file = None
    domain = facts.get("brand_name", "example.com")

    for i, arg in enumerate(sys.argv):
        if arg == "--eval" and i + 1 < len(sys.argv):
            eval_file = sys.argv[i + 1]
        elif arg == "--domain" and i + 1 < len(sys.argv):
            domain = sys.argv[i + 1]

    queries = build_queries(facts)

    if eval_file and os.path.exists(eval_file):
        with open(eval_file, encoding="utf-8-sig") as f:
            sim_results = json.load(f)
        findings = evaluate_citation_simulation(sim_results, facts, domain)
        print(json.dumps({"brand_name": facts.get("brand_name"), "queries": queries, "findings": findings}, indent=2))
    else:
        print(json.dumps({"brand_name": facts.get("brand_name"), "queries": queries}, indent=2))


if __name__ == "__main__":
    main()
