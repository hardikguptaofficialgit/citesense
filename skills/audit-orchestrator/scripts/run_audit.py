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
from generate_queries import build_queries, evaluate_citation_simulation
from corroboration_scorer import score_fact, assess_collision_risk, generate_trust_findings
from compose_report import build_final_report, assign_ids_and_validate


def generate_proactive_recommendations(inventory: SiteInventory) -> list:
    """Generates beyond-defect optimization recommendations to improve AI readiness."""
    proactive = []
    
    # 1. FAQPage structured data recommendation if question-like content exists
    has_faq_schema = False
    has_faq_content = False
    for snap in inventory.pages.values():
        for ent in snap.get("jsonld_parsed", []):
            if ent.get("@type") == "FAQPage":
                has_faq_schema = True
        text = snap.get("visible_text", "")
        if any(q in text.lower() for q in ("frequently asked", "faq", "how does", "what is", "how do i")):
            has_faq_content = True

    if has_faq_content and not has_faq_schema:
        proactive.append({
            "title": "Add Schema.org FAQPage markup to enrich AI assistant direct answers",
            "rationale": "The site contains informative Q&A or FAQ text. Adding structured FAQPage JSON-LD allows search engines and generative AI agents to quote verbatim answers directly in response to user inquiries.",
            "suggested_action": {
                "summary": "Implement Schema.org FAQPage structured data on help and FAQ sections.",
                "priority": "medium",
                "how_to_fix": "Wrap top customer questions in a JSON-LD script declaring @type 'FAQPage' with 'mainEntity' Question and acceptedAnswer Answer objects."
            }
        })

    # 2. llms.txt protocol recommendation if not present
    if not inventory.special_files.get("llms_txt", {}).get("found"):
        proactive.append({
            "title": "Publish an llms.txt file to guide AI assistants to authoritative documentation",
            "rationale": "Emerging AI web standards like /llms.txt provide large language models with a curated, markdown-formatted directory of core brand documentation and APIs.",
            "suggested_action": {
                "summary": "Create an llms.txt file in the root web directory.",
                "priority": "low",
                "how_to_fix": "Add an /llms.txt file containing markdown links to your primary product, documentation, pricing, and company overview pages."
            }
        })

    return proactive


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

    # Step 5: citation-simulator (Generate queries & score simulated checks)
    gt = inventory.ground_truth
    queries = build_queries(gt)
    # Perform citation evaluation checks based on ground truth availability
    # (If offline, evaluate baseline discoverability of ground truth)
    citation_findings = []
    # If robots blocks root, citation simulation observes that AI queries will be omitted
    robots_blocked = any(f.get("category") == "crawlability" and f.get("severity") in ("critical", "high") for f in crawl_findings)
    if robots_blocked:
        citation_sim_results = [{
            "query": f"What is {gt.get('brand_name')}?",
            "classification": "omission",
            "category": "identity",
            "surfaced_urls": [],
            "evidence": f"Brand domain is blocked by robots.txt, causing AI search engines to omit official {gt.get('brand_name')} pages from answer synthesis."
        }]
        citation_findings = evaluate_citation_simulation(citation_sim_results, gt, inventory.origin.replace("https://", "").replace("http://", ""))
        all_candidate_findings.extend(citation_findings)

    # Step 6: trust-corroboration-graph
    # Verify core claims extracted in ground truth
    facts_to_score = []
    if gt.get("key_facts", {}).get("founding_year"):
        facts_to_score.append({
            "fact": f"Founded in {gt['key_facts']['founding_year']}",
            "sources": [{"domain": inventory.origin, "is_brand_owned": True, "supports_fact": True, "evidence": "Site mention"}]
        })
    trust_findings = generate_trust_findings(
        fact_scores=[score_fact(f) for f in facts_to_score],
        collision_assessment=assess_collision_risk([], {}),
        brand_name=gt.get("brand_name", "Brand"),
        site_url=inventory.origin
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
