#!/usr/bin/env python3
"""
corroboration_scorer.py -- Evaluates external claim corroboration and entity disambiguation risk.
Emits structured CandidateFindings with verifiable evidence and confidence ratings.
"""
import os
import sys
import json
from typing import List, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from models import create_candidate_finding, CandidateFinding


AUTHORITY_DOMAINS = (
    "wikipedia.org", "wikidata.org", "crunchbase.com", "linkedin.com",
    "github.com", "bloomberg.com", "reuters.com", "sec.gov",
    "opencorporates.com", "g2.com", "trustpilot.com", "glassdoor.com",
    "bbb.org", "companieshouse.gov.uk", "producthunt.com",
)


def evaluate_identity_anchoring(
    brand_name: str,
    site_url: str,
    same_as_urls: List[str],
    external_link_domains: List[str],
    has_org_schema: bool,
    readable_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Observable, on-site half of Appendix D: is there any machine-readable path from this
    brand to an independent authority that could corroborate or disambiguate it?

    This reports only what was directly observed in the crawl. It never claims to have
    searched the web -- that path is `score_fact()` / `assess_collision_risk()` below,
    which require an agent to supply real third-party search results.
    """
    findings = []
    if readable_pages == 0:
        # Missing anchors cannot be observed when no page was readable. The orchestrator
        # records this in its access summary; emitting a trust defect here would be fabricated
        # evidence, just like treating an unreadable page as missing schema.
        return findings

    anchor_domains = sorted({
        d for d in external_link_domains
        if any(d == a or d.endswith("." + a) for a in AUTHORITY_DOMAINS)
    })
    same_as_anchors = sorted({
        u for u in same_as_urls
        if any(a in u.lower() for a in AUTHORITY_DOMAINS)
    })

    if same_as_anchors or anchor_domains:
        return findings

    schema_state = (
        "Organization schema is present but declares 0 sameAs URIs"
        if has_org_schema else
        "no Organization schema is present, so no sameAs URIs can be declared"
    )
    findings.append(create_candidate_finding(
        title=f"Brand identity is not anchored to any independent authority source",
        category="corroboration",
        severity="medium",
        url=site_url,
        observation=(
            f"Across the crawled pages, {schema_state}, and 0 of {len(set(external_link_domains))} "
            f"distinct outbound link domains point to an independent authority "
            f"(Wikipedia, Wikidata, Crunchbase, LinkedIn, GitHub, regulatory registries). "
            f"An assistant resolving \"{brand_name}\" therefore has no machine-readable route from "
            f"this site to a corroborating third party, and no way to tell it apart from other "
            f"entities sharing the name."
        ),
        method="onsite_identity_anchor_inspection",
        source_skill="trust-corroboration-graph",
        action_summary="Publish machine-readable identity anchors linking the brand to independent authorities.",
        action_priority="medium",
        action_how_to_fix=(
            "Add Organization JSON-LD with a stable @id, legalName, and a sameAs array pointing to "
            "the brand's Wikidata item, Wikipedia article, LinkedIn company page and Crunchbase profile. "
            "Create those external profiles first if they do not exist -- sameAs pointing at nothing "
            "does not corroborate anything."
        ),
        fingerprint="trust:no-independent-identity-anchor",
        status="confirmed",
        confidence="high",
        impact="medium"
    ).to_dict())

    return findings


def score_fact(fact_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Scores independent corroboration strength for a single fact claim."""
    sources = fact_obj.get("sources", [])
    independent = [s for s in sources if not s.get("is_brand_owned")]
    supporting = [s for s in independent if s.get("supports_fact") is True and s.get("evidence")]
    contradicting = [s for s in independent if s.get("supports_fact") is False and s.get("evidence")]
    
    domains_supporting = sorted(set(s["domain"] for s in supporting))
    domains_contradicting = sorted(set(s["domain"] for s in contradicting))

    if len(domains_supporting) >= 2 and not domains_contradicting:
        strength = "strong"
    elif len(domains_supporting) == 1 and not domains_contradicting:
        strength = "weak"
    elif domains_contradicting and domains_supporting:
        strength = "contested"
    elif domains_contradicting and not domains_supporting:
        strength = "contradicted"
    else:
        strength = "uncorroborated"

    return {
        "fact": fact_obj.get("fact"),
        "independent_supporting_domains": domains_supporting,
        "independent_contradicting_domains": domains_contradicting,
        "corroboration_strength": strength
    }


def assess_collision_risk(name_collisions: List[Dict[str, Any]], markers: Dict[str, bool]) -> Dict[str, Any]:
    """Assesses entity collision risk considering industry adjacency and disambiguating markers."""
    if not name_collisions:
        return {"risk": "none_detected", "collisions_found": []}

    plausible = [
        c for c in name_collisions
        if isinstance(c, dict) and c.get("domain") and c.get("same_or_adjacent_industry")
    ]
    if not plausible:
        return {
            "risk": "none_detected",
            "collisions_found": [],
            "note": "No verified plausible same-name collision in same or adjacent industry."
        }

    marker_count = sum(1 for v in (markers or {}).values() if v)
    risk = "high" if marker_count == 0 else ("medium" if marker_count == 1 else "low")
    return {
        "risk": risk,
        "collisions_found": plausible,
        "disambiguating_markers_present": markers,
        "note": "Risk is high only for verified plausible same-name collisions with no machine-readable disambiguation."
    }


def generate_trust_findings(
    fact_scores: List[Dict[str, Any]],
    collision_assessment: Dict[str, Any],
    brand_name: str,
    site_url: str = "https://example.com"
) -> List[Dict[str, Any]]:
    """Generates structured CandidateFindings from corroboration scores and collision risk."""
    findings = []

    # Corroboration findings
    for f in fact_scores:
        strength = f.get("corroboration_strength")
        fact_text = f.get("fact", "")
        supp = f.get("independent_supporting_domains", [])
        contra = f.get("independent_contradicting_domains", [])

        if strength in ("uncorroborated", "contradicted"):
            f_item = create_candidate_finding(
                title=f"Core claim lacks independent external corroboration: \"{fact_text[:45]}\"",
                category="corroboration",
                severity="medium",
                url=site_url,
                observation=f"Searched external sources for claim \"{fact_text}\"; found 0 independent authoritative supporting sources. Only source is brand-owned channels.",
                method="external_knowledge_graph_search",
                source_skill="trust-corroboration-graph",
                action_summary="Establish external corroboration on authoritative third-party platforms.",
                action_priority="medium",
                action_how_to_fix="Verify company details and notable claims on Wikipedia/Wikidata, Crunchbase, LinkedIn company page, and industry registries.",
                fingerprint=f"trust:uncorroborated-fact:{fact_text[:30]}",
                status="likely-risk",
                confidence="high",
                impact="medium"
            )
            findings.append(f_item.to_dict())

        elif strength == "contested":
            f_item = create_candidate_finding(
                title=f"Contradictory third-party claims found for fact: \"{fact_text[:45]}\"",
                category="corroboration",
                severity="high",
                url=site_url,
                observation=f"Third-party sources conflict on \"{fact_text}\". Supporting: {', '.join(supp)}. Contradicting: {', '.join(contra)}.",
                method="external_knowledge_graph_search",
                source_skill="trust-corroboration-graph",
                action_summary="Clarify canonical brand claim in press materials and structured data.",
                action_priority="high",
                action_how_to_fix="Publish authoritative statement and update external directory listings to resolve third-party conflicts.",
                fingerprint=f"trust:contested-fact:{fact_text[:30]}",
                status="confirmed",
                confidence="high",
                impact="high"
            )
            findings.append(f_item.to_dict())

    # Entity collision findings
    risk = collision_assessment.get("risk", "none_detected")
    collisions = collision_assessment.get("collisions_found", [])

    if risk in ("high", "medium") and collisions:
        colliding_domains = [c.get("domain") for c in collisions if c.get("domain")]
        f_item = create_candidate_finding(
            title=f"High risk of AI entity confusion due to name collision with {', '.join(colliding_domains[:2])}",
            category="entity-disambiguation",
            severity="critical" if risk == "high" else "high",
            url=site_url,
            observation=f"Plausible name collision with {', '.join(colliding_domains)} in the same/adjacent market, and site lacks sufficient disambiguating markers (sameAs links, legal entity schema).",
            method="entity_collision_evaluation",
            source_skill="trust-corroboration-graph",
            action_summary="Add robust Schema.org sameAs links and legal entity disambiguation.",
            action_priority="critical" if risk == "high" else "high",
            action_how_to_fix="Add Organization JSON-LD with unique @id, legalName, sameAs pointing to Wikidata/Wikipedia, and geographic location.",
            fingerprint=f"trust:entity-collision:{brand_name.lower()}",
            status="likely-risk" if risk == "medium" else "confirmed",
            confidence="high",
            impact="critical" if risk == "high" else "high"
        )
        findings.append(f_item.to_dict())

    return findings


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: corroboration_scorer.py '<json_input_or_file>' [--findings-only]"})); sys.exit(1)

    input_arg = sys.argv[1]
    if os.path.exists(input_arg):
        with open(input_arg, encoding="utf-8-sig") as f:
            data = json.load(f)
    else:
        try:
            data = json.loads(input_arg)
        except Exception as e:
            print(json.dumps({"error": f"invalid JSON input: {e}"})); sys.exit(1)

    facts = data.get("facts", [])
    collisions = data.get("name_collisions_found", [])
    markers = data.get("disambiguating_markers_present", {})
    brand_name = data.get("brand_name", "Brand")
    site_url = data.get("site_url", "https://example.com")

    fact_scores = [score_fact(f) for f in facts]
    collision_assessment = assess_collision_risk(collisions, markers)
    findings = generate_trust_findings(fact_scores, collision_assessment, brand_name, site_url)

    if "--findings-only" in sys.argv:
        print(json.dumps(findings, indent=2))
    else:
        out = {
            "fact_corroboration": fact_scores,
            "weak_or_worse_facts": [f for f in fact_scores if f["corroboration_strength"] in ("weak", "contested", "contradicted", "uncorroborated")],
            "entity_collision_assessment": collision_assessment,
            "findings": findings
        }
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
