---
name: citation-simulator
description: Simulates how a real AI assistant would answer common questions about the brand by actually performing the search-fetch-extract loop described in Appendix B, then classifies each result as correctly answered, omitted, misattributed to the wrong entity, stale, or contradicted across sources. Produces direct evidence that a discoverability problem causes a real answer failure.
---

# Citation Simulator (proof-of-failure, not just structural inference)

## Why this skill exists
The other discoverability skills infer failure from structural signals (missing schema, a blocked crawler, JS-gated content). This skill closes the loop: it tests the search-fetch-extract cycle for realistic questions about the brand, and directly observes whether the simulated answer comes out right.

Run **after** `crawl-render-audit` and `freshness-corroboration` have produced ground-truth extraction.

## Inputs
- `ground_truth`: `{"brand_name": "...", "category": "...", "location": "...", "key_facts": {...}}`
- `site_domain`: the brand's own domain.

## Procedure
1. Run `python3 skills/citation-simulator/scripts/generate_queries.py '<ground_truth_json>'`.
2. Evaluates queries across identity, offering, transactional, differentiation, and credibility.
3. Classifies results against confirmed ground truth:
   - **Correct** -- cites the brand's own domain or an accurate third party. No finding.
   - **Omission** -- brand content omitted from top results for an indexable fact -> `citation-omission`.
   - **Misattribution** -- confused with another entity -> `citation-misattribution`, **critical**.
   - **Staleness** -- relies on outdated figures contradicting ground truth -> `citation-staleness`.
   - **Contradiction** -- top sources conflict on core facts -> `citation-contradiction`.

## Output
JSON array of structured `CandidateFinding` objects:
```json
{
  "title": "AI search simulation: brand content omitted for \"How much does Acme Widgets cost?\"",
  "category": "citation-omission",
  "severity": "high",
  "status": "confirmed",
  "confidence": "high",
  "impact": "high",
  "evidence": "Observed at https://example.com via simulated_ai_search_loop [2026-08-29T17:45:00Z]: Simulated query \"How much does Acme Widgets cost?\" failed to surface official brand URLs in top results. (Confidence: high)",
  "source_skill": "citation-simulator",
  "fingerprint": "citation:omission:transactional:pricing",
  "suggested_action": {
    "summary": "Ensure the pricing page is crawlable, linked from the homepage, and marked up with Product/Offer schema.",
    "priority": "high",
    "how_to_fix": "Add Product/Offer JSON-LD to /pricing and verify robots.txt allows retrieval bots."
  }
}
```
Return candidate findings as a JSON array to the orchestrator.
