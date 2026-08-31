#!/usr/bin/env python3
"""
run_audit.py -- Main end-to-end audit orchestrator entrypoint.
Crawls the site once into a shared SiteInventory, executes all specialist audit skills,
merges CandidateFindings, generates proactive recommendations, and outputs the final validated report.
"""
import sys
import os
import json
import argparse
import time
from urllib.parse import urlparse

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
freshness_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../freshness-corroboration/scripts"))
engagement_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../engagement-audit/scripts"))
citation_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../citation-simulator/scripts"))
trust_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../trust-corroboration-graph/scripts"))

for d in (current_dir, crawl_scripts_dir, freshness_scripts_dir, engagement_scripts_dir, citation_scripts_dir, trust_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from site_inventory import SiteInventory
from crawlability_check import evaluate_crawlability
from render_and_data_scan import evaluate_render_and_data_scan
from freshness_and_consistency_scan import evaluate_freshness_and_consistency
from engagement_scan import evaluate_engagement_audit
from generate_queries import evaluate_answerability
from corroboration_scorer import evaluate_identity_anchoring
from compose_report import build_final_report
from proactive_recommendations import generate_proactive_recommendations

# NOTE: the agent-supplied halves of citation-simulator and trust-corroboration-graph
# (evaluate_citation_simulation, score_fact, assess_collision_risk, generate_trust_findings)
# are intentionally NOT imported here. They require real third-party search results; calling
# them with invented inputs is the bug F8 removed. Reach them via the standalone skill CLIs.


def run_full_audit(
    site_url: str,
    max_pages: int = 5,
    timeout: int = 8,
    save_inventory_path: str = None
) -> dict:
    """Executes the complete audit pipeline using the single-pass SiteInventory."""
    start_time = time.time()
    
    # Step 1: Shared SiteInventory Crawl (Crawled ONCE)
    inventory = SiteInventory(site_url)
    inventory.crawl_site(max_pages=max_pages, timeout=timeout)
    if save_inventory_path:
        inventory.save_json(save_inventory_path)

    all_candidate_findings = []

    # Step 2: crawl-render-audit
    crawl_findings = evaluate_crawlability(inventory)
    render_findings = evaluate_render_and_data_scan(inventory)
    all_candidate_findings.extend(crawl_findings)
    all_candidate_findings.extend(render_findings)

    # Step 3: freshness-corroboration
    freshness_findings = evaluate_freshness_and_consistency(inventory)
    all_candidate_findings.extend(freshness_findings)

    # Step 4: engagement-audit
    engagement_findings = evaluate_engagement_audit(inventory)
    all_candidate_findings.extend(engagement_findings)

    # Step 5: citation-simulator
    # Runs on every site. Tests the last step of the Appendix-B loop deterministically: given the
    # pages we actually fetched, could an assistant quote an answer to a natural question about
    # this brand? No hardcoded results, and no claim to have run a live web search.
    gt = inventory.ground_truth
    site_domain = inventory.origin.replace("https://", "").replace("http://", "")
    citation_findings = evaluate_answerability(inventory.to_dict(), gt, site_domain)
    all_candidate_findings.extend(citation_findings)

    # Step 6: trust-corroboration-graph
    # Observable half only: does any machine-readable path exist from this site to an independent
    # authority? The score_fact()/assess_collision_risk() path needs real third-party search
    # results and is exposed via the skill's standalone CLI for agent-driven runs -- it is
    # deliberately NOT invoked here, because inventing sources would fabricate the evidence.
    same_as_urls = list(gt.get("same_as", []) or [])
    external_domains = []
    has_org_schema = False
    for snap in inventory.pages.values():
        if snap.get("inconclusive") or snap.get("status_code") != 200:
            continue
        for link in snap.get("external_links", []):
            netloc = urlparse(link.get("href", "")).netloc.lower()
            if netloc:
                external_domains.append(netloc[4:] if netloc.startswith("www.") else netloc)
        for ent in snap.get("jsonld_parsed", []):
            t = ent.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Organization", "LocalBusiness", "Corporation", "Brand") for x in types):
                has_org_schema = True
                sa = ent.get("sameAs")
                if sa:
                    same_as_urls.extend(sa if isinstance(sa, list) else [sa])

    trust_findings = evaluate_identity_anchoring(
        brand_name=gt.get("brand_name", "Brand"),
        site_url=inventory.origin,
        same_as_urls=same_as_urls,
        external_link_domains=external_domains,
        has_org_schema=has_org_schema
    )
    all_candidate_findings.extend(trust_findings)

    # Step 7: Proactive Recommendations
    proactive = generate_proactive_recommendations(inventory)

    # Step 8: Assemble, Deduplicate, Prioritize & Format Report
    report = build_final_report(
        site_url=inventory.origin,
        findings=all_candidate_findings,
        proactive_recommendations=proactive
    )

    return report


def main():
    parser = argparse.ArgumentParser(description="Brand AI-Readiness Audit Orchestrator")
    parser.add_argument("site_url", help="URL of the website to audit")
    parser.add_argument("--output", "-o", help="Filepath to write the final JSON report")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum number of pages to sample (default: 5)")
    parser.add_argument("--timeout", type=int, default=8, help="HTTP timeout in seconds (default: 8)")
    parser.add_argument("--save-inventory", help="Optional path to save raw SiteInventory JSON")

    args = parser.parse_args()
    report = run_full_audit(
        site_url=args.site_url,
        max_pages=args.max_pages,
        timeout=args.timeout,
        save_inventory_path=args.save_inventory
    )

    report_json = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_json)
        print(json.dumps({
            "status": "completed",
            "output": args.output,
            "site": report["site"],
            "total_findings": report["summary"]["total_findings"],
            "summary": report["summary"]
        }, indent=2))
    else:
        print(report_json)


if __name__ == "__main__":
    main()
