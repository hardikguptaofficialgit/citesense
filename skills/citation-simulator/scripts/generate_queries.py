#!/usr/bin/env python3
"""
generate_queries.py -- Deterministic query generation and citation simulation evaluation.
Generates realistic entity-grounded questions and classifies search/citation simulation results.
Emits structured CandidateFindings.
"""
import os
import sys
import json
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
