#!/usr/bin/env python3
"""corroboration_scorer.py -- deterministic scoring layer for trust-corroboration-graph.
Does NOT search the web itself; scores sources the calling agent already gathered via its
own search tool. Usage: python3 corroboration_scorer.py '<json input>'
Input shape: {"facts": [{"fact": str, "sources": [{"domain","is_brand_owned","supports_fact"}]}],
"name_collisions_found": [str], "disambiguating_markers_present": {marker: bool}}"""
import sys, json

def score_fact(fact_obj):
    sources = fact_obj.get("sources", [])
    independent = [s for s in sources if not s.get("is_brand_owned")]
    # A search failure/unknown is not counter-evidence.  Count only sources with quoted,
    # claim-level support supplied by the caller.
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
    return {"fact": fact_obj.get("fact"), "independent_supporting_domains": domains_supporting,
            "independent_contradicting_domains": domains_contradicting, "corroboration_strength": strength}

def assess_collision_risk(name_collisions, markers):
    if not name_collisions:
        return {"risk": "none_detected", "collisions_found": []}
    # Only verified, plausible collisions qualify; unrelated matching strings must not create a finding.
    plausible=[c for c in name_collisions if isinstance(c,dict) and c.get("domain") and c.get("same_or_adjacent_industry")]
    if not plausible: return {"risk":"none_detected","collisions_found":[],"note":"No verified plausible same-name collision supplied."}
    marker_count = sum(1 for v in (markers or {}).values() if v)
    risk = "high" if marker_count == 0 else ("medium" if marker_count == 1 else "low")
    return {"risk": risk, "collisions_found": name_collisions, "disambiguating_markers_present": markers,
            "note": "risk is high only for verified plausible same-name collisions plus no machine-readable disambiguation"}

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: corroboration_scorer.py '<json input>'"})); sys.exit(1)
    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON input: {e}"})); sys.exit(1)
    fact_scores = [score_fact(f) for f in data.get("facts", [])]
    collision_assessment = assess_collision_risk(data.get("name_collisions_found", []), data.get("disambiguating_markers_present", {}))
    print(json.dumps({"fact_corroboration": fact_scores,
                       "weak_or_worse_facts": [f for f in fact_scores if f["corroboration_strength"] in ("weak", "contested", "contradicted", "uncorroborated")],
                       "entity_collision_assessment": collision_assessment}, indent=2))

if __name__ == "__main__":
    main()
