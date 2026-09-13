#!/usr/bin/env python3
"""
crawlability_check.py -- Audits robots.txt rules, sitemaps, and AI discovery protocols.
Returns structured CandidateFindings with verifiable evidence and diagnostic data.
"""
import os
import sys
import json
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from audit_common import (
    AI_USER_AGENTS, CITATION_CRITICAL_AGENTS, crawler_class,
    parse_robots, robot_decision, safe_fetch, DEFAULT_TIMEOUT
)
from models import create_candidate_finding, CandidateFinding
from site_inventory import SiteInventory, get_or_crawl_inventory


def evaluate_crawlability(inventory: SiteInventory) -> List[Dict[str, Any]]:
    """Evaluates crawlability signals from SiteInventory and emits CandidateFindings."""
    findings = []
    robots_data = inventory.robots_txt
    origin = inventory.origin
    robots_url = robots_data.get("url") or urljoin(origin, "/robots.txt")

    if robots_data.get("found"):
        decisions = robots_data.get("agent_decisions", {})
        partially_blocked = robots_data.get("partially_blocked_agents", {})
        raw_robots = robots_data.get("raw", "")

        # Check for broad or AI-specific crawler blocks
        root_blocked_agents = [
            agent for agent, path_map in decisions.items()
            if not path_map.get("/", {}).get("allowed", True)
        ]
        
        # Check wildcard status
        groups = parse_robots(raw_robots)
        wildcard_root_allowed = robot_decision(groups, "*", "/")["allowed"]

        if root_blocked_agents:
            if not wildcard_root_allowed:
                # Site-wide block
                f = create_candidate_finding(
                    title="Root site is disallowed for all crawlers including AI retrieval agents",
                    category="crawlability",
                    severity="critical",
                    url=robots_url,
                    observation=f"robots.txt disallows root '/' for user-agent '*', blocking all AI bots ({', '.join(root_blocked_agents[:4])}).",
                    method="robots_txt_parser_longest_match",
                    source_skill="crawl-render-audit",
                    action_summary="Update robots.txt to allow crawling of public landing and product pages.",
                    action_priority="critical",
                    action_how_to_fix="Ensure 'User-agent: * / Disallow: /' is removed or narrowed to private authenticated directories only.",
                    fingerprint="robots:disallow-all-root",
                    status="confirmed",
                    confidence="high",
                    impact="critical"
                )
                findings.append(f.to_dict())
            else:
                # Selective AI bot block. Severity depends entirely on WHICH class is blocked:
                # blocking training crawlers costs no citations and is a legitimate licensing
                # stance; blocking search-index or user-triggered agents is what makes a brand
                # uncitable. Flagging both alike was a false positive against deliberate policy.
                blocked_citation = [a for a in root_blocked_agents if a in CITATION_CRITICAL_AGENTS]
                blocked_training = [a for a in root_blocked_agents if crawler_class(a) == "training"]

                if blocked_citation:
                    f = create_candidate_finding(
                        title=f"AI search and retrieval crawlers blocked from root ({', '.join(blocked_citation[:3])})",
                        category="crawlability",
                        severity="critical",
                        url=robots_url,
                        observation=(
                            f"robots.txt disallows root '/' for retrieval agents: {', '.join(blocked_citation)}. "
                            f"These build the indexes AI answers are assembled from, or fetch a page live when a "
                            f"user asks about it, so the brand cannot be cited at all. "
                            + (f"Training-only crawlers ({', '.join(blocked_training)}) are also blocked, which is a "
                               f"separate and legitimate licensing choice." if blocked_training else "")
                        ),
                        method="robots_txt_parser_longest_match",
                        source_skill="crawl-render-audit",
                        action_summary="Allow AI search and user-triggered retrieval agents, even if training crawlers stay blocked.",
                        action_priority="critical",
                        action_how_to_fix=(
                            "In robots.txt, allow OAI-SearchBot, Claude-SearchBot and PerplexityBot (search indexes) "
                            "and ChatGPT-User, Claude-User and Perplexity-User (live user fetches). You can keep "
                            "GPTBot, ClaudeBot, Google-Extended and CCBot disallowed if you do not want your content "
                            "used for model training -- the two decisions are independent."
                        ),
                        fingerprint="robots:citation-agents-blocked-root",
                        status="confirmed",
                        confidence="high",
                        impact="critical"
                    )
                    findings.append(f.to_dict())
                elif blocked_training:
                    # Coherent policy, not a defect. Recorded so the report shows we saw it.
                    f = create_candidate_finding(
                        title="Training-only AI crawlers are blocked; search and retrieval agents remain allowed",
                        category="crawlability",
                        severity="low",
                        url=robots_url,
                        observation=(
                            f"robots.txt disallows root '/' for training crawlers ({', '.join(blocked_training)}) "
                            f"while leaving search-index and user-triggered agents allowed. This is a coherent "
                            f"licensing stance and does not prevent the brand being cited in AI answers."
                        ),
                        method="robots_txt_parser_longest_match",
                        source_skill="crawl-render-audit",
                        action_summary="No change needed; confirm this is intentional and state the policy explicitly.",
                        action_priority="low",
                        action_how_to_fix=(
                            "If deliberate, make it legible by adding a Content Signals Policy block or RSL licensing "
                            "terms to robots.txt so the distinction between training and retrieval is machine-readable "
                            "rather than inferred from which agents you named."
                        ),
                        fingerprint="robots:training-only-blocked",
                        status="proactive",
                        confidence="high",
                        impact="low"
                    )
                    findings.append(f.to_dict())
        elif partially_blocked:
            # Subpath blocked
            sample_blocks = []
            for agent, paths in list(partially_blocked.items())[:3]:
                sample_blocks.append(f"{agent} blocked on {', '.join(paths)}")
            f = create_candidate_finding(
                title="AI crawlers are restricted on key content or commercial subpaths",
                category="crawlability",
                severity="medium",
                url=robots_url,
                observation=f"robots.txt blocks specific subpaths for AI crawlers: {'; '.join(sample_blocks)}.",
                method="robots_txt_parser_longest_match",
                source_skill="crawl-render-audit",
                action_summary="Review subpath disallow directives to prevent accidental blocking of public documentation or products.",
                action_priority="medium",
                action_how_to_fix="Review disallowed paths in robots.txt and add scoped 'Allow:' directives for public documentation, pricing, and FAQ paths.",
                fingerprint="robots:subpath-restrictions",
                status="likely-risk",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())
    else:
        # No robots.txt or fetch error
        status = robots_data.get("status")
        if status == 404:
            # 404 is valid default allow, not a failure, but noted as low/proactive
            pass
        elif status is not None and status >= 500:
            # Server error
            f = create_candidate_finding(
                title="Server error encountered when fetching robots.txt",
                category="crawlability",
                severity="medium",
                url=robots_url,
                observation=f"Fetching robots.txt returned HTTP {status}, causing search crawlers to potentially delay or throttle indexing.",
                method="http_get",
                source_skill="crawl-render-audit",
                action_summary="Ensure robots.txt returns a stable 200 HTTP response or valid 404.",
                action_priority="medium",
                action_how_to_fix="Check server routing and static file handling for /robots.txt to prevent 5xx gateway errors.",
                fingerprint="robots:server-error-5xx",
                status="confirmed",
                confidence="high",
                impact="medium"
            )
            findings.append(f.to_dict())

    # Sitemaps Check
    sitemaps = inventory.sitemaps
    valid_sitemaps = [s for s in sitemaps if s.get("found")]
    sitemaps_declared = robots_data.get("sitemaps_declared", [])
    readable_pages = int((inventory.crawl_budget or {}).get("readable_pages", 0) or 0)
    if not readable_pages:
        readable_pages = sum(
            1 for page in (inventory.pages or {}).values()
            if not page.get("inconclusive") and page.get("status_code") == 200
        )

    if readable_pages and not valid_sitemaps and not sitemaps_declared:
        f = create_candidate_finding(
            title="Missing XML sitemap declared in robots.txt or available at /sitemap.xml",
            category="crawlability",
            severity="medium",
            url=urljoin(origin, "/sitemap.xml"),
            observation=f"Request to {urljoin(origin, '/sitemap.xml')} did not return a valid sitemap and no 'Sitemap:' directive was found in robots.txt.",
            method="http_get_sitemap_check",
            source_skill="crawl-render-audit",
            action_summary="Publish an XML sitemap and declare its location in robots.txt.",
            action_priority="medium",
            action_how_to_fix="Generate an XML sitemap for public indexable URLs and add 'Sitemap: https://yourdomain.com/sitemap.xml' to robots.txt.",
            fingerprint="crawl:missing-xml-sitemap",
            status="confirmed",
            confidence="high",
            impact="medium"
        )
        findings.append(f.to_dict())

    return findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: crawlability_check.py <url_or_inventory_json> [--findings-only]"})); sys.exit(1)

    target = sys.argv[1]
    inventory = get_or_crawl_inventory(target)
    findings = evaluate_crawlability(inventory)

    if "--findings-only" in sys.argv:
        print(json.dumps(findings, indent=2))
    else:
        out = {
            "site": inventory.origin,
            "budget": inventory.crawl_budget,
            "checks": {
                "robots_txt": inventory.robots_txt,
                "sitemaps": inventory.sitemaps,
                "special_files": inventory.special_files
            },
            "findings": findings
        }
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
