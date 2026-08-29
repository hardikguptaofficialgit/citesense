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

from audit_common import AI_USER_AGENTS, parse_robots, robot_decision, safe_fetch, DEFAULT_TIMEOUT
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
                # Selective AI bot block
                f = create_candidate_finding(
                    title=f"AI crawlers explicitly blocked from root pages ({', '.join(root_blocked_agents[:3])})",
                    category="crawlability",
                    severity="critical" if "GPTBot" in root_blocked_agents or "ClaudeBot" in root_blocked_agents else "high",
                    url=robots_url,
                    observation=f"robots.txt disallows root '/' specifically for: {', '.join(root_blocked_agents)}, while general crawler access is permitted.",
                    method="robots_txt_parser_longest_match",
                    source_skill="crawl-render-audit",
                    action_summary="Allow AI search and retrieval crawlers to access public brand content.",
                    action_priority="high",
                    action_how_to_fix="In robots.txt, remove explicit Disallow rules for retrieval agents (e.g., GPTBot, ClaudeBot, PerplexityBot) or replace them with granular directory restrictions.",
                    fingerprint="robots:ai-agents-blocked-root",
                    status="confirmed",
                    confidence="high",
                    impact="high"
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

    if not valid_sitemaps and not sitemaps_declared:
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
