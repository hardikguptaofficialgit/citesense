---
name: trust-corroboration-graph
description: Checks whether independent third-party sources corroborate a brand's core claims, and whether the brand can be reliably disambiguated from other entities sharing its name. Uses claim scoring and entity collision risk assessment with Schema.org sameAs links.
license: MIT
allowed-tools: Bash, Read, WebSearch, WebFetch
---

# Trust & Corroboration Graph (Appendix D, identity half)

Invoked by `audit-orchestrator`. Two modes. **Observable** (`evaluate_identity_anchoring`, runs on every audit): does any machine-readable path exist from this site to an independent authority -- Organization `sameAs` URIs, or outbound links to Wikidata/Wikipedia/Crunchbase/LinkedIn/regulatory registries? **Agent-supplied** (`score_fact`, `assess_collision_risk`): scores real third-party corroboration and same-name collision risk from search results an agent provides. The observable mode never claims to have searched the web.

## Inputs
- `brand_name`, `category`, `location` (from ground truth)
- `facts`: list of claim objects with supporting/contradicting independent sources
- `name_collisions_found`: list of colliding entities with industry context
- `disambiguating_markers_present`: dict of marker presence (`sameAs`, legal name, org schema)

## Procedure
1. Run `python3 skills/trust-corroboration-graph/scripts/corroboration_scorer.py '<json_data>' --findings-only`.
2. **Corroboration Evaluation:**
   - Independent sources require verifiable quotes/evidence.
   - `uncorroborated`/`contradicted` on core identity -> **medium** / **high**.
   - `contested` (independent sources contradict each other) -> **high**.
3. **Entity Disambiguation:**
   - Verifies plausible same/adjacent market collisions.
   - High risk (plausible collision without `sameAs` or Organization disambiguation) -> **critical** / **high**.

## Output
JSON array of structured `CandidateFinding` objects:
```json
{
  "title": "High risk of AI entity confusion due to name collision with acme-corp.com",
  "category": "entity-disambiguation",
  "severity": "high",
  "status": "confirmed",
  "confidence": "high",
  "impact": "high",
  "evidence": "Observed at https://example.com via entity_collision_evaluation [2026-08-29T17:45:00Z]: Plausible name collision with acme-corp.com in the same market; site lacks sameAs disambiguation links. (Confidence: high)",
  "source_skill": "trust-corroboration-graph",
  "fingerprint": "trust:entity-collision:acme",
  "suggested_action": {
    "summary": "Add robust Schema.org sameAs links and legal entity disambiguation.",
    "priority": "high",
    "how_to_fix": "Add Organization JSON-LD with unique @id, legalName, and sameAs pointing to Wikidata/Wikipedia."
  }
}
```
Return candidate findings as a JSON array to the orchestrator.
