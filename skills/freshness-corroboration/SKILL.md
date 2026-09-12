---
name: freshness-corroboration
description: Checks whether a site's facts are current and internally self-consistent using a claim-based model -- stale time-sensitive claims, expired promotions/webinars, and contradictions between what different pages on the SAME site say (e.g. founding year or phone number disagreeing between the footer and the About page). Use when diagnosing whether outdated or self-contradictory content is undermining a brand's trustworthiness to AI assistants. Does not treat missing dateModified as a defect.
license: MIT
allowed-tools: Bash, Read
---

# Freshness & Internal Consistency Audit (Appendix D, temporal half)

Invoked by `audit-orchestrator` after `crawl-render-audit`. Scope is internal and claim-based: does the site's own content agree with itself, and are time-sensitive claims current? Missing `dateModified` or `datePublished` alone is **not** a defect.

## Inputs
- `inventory`: a loaded `SiteInventory` object or list of page URLs.

## Procedure
1. Run `python3 skills/freshness-corroboration/scripts/freshness_and_consistency_scan.py <inventory_json_or_url> --findings-only`.
2. **Cross-Page Contradictions:**
   - Any `founding_year_mismatch` -> **high**: contradictory claims actively damage AI engine trust.
   - Any `phone_number_mismatch` across pages without branch context -> **medium**.
3. **Claim-Based Freshness:**
   - Active time-sensitive offers, webinars, or pricing referencing expired past years (>= 2 years old) -> **medium**.
   - Severely outdated copyright notices (3+ years gap) -> **low**.
4. False-positive guardrail: Never flag the absence of `dateModified` as a defect.

## Output
JSON array of structured `CandidateFinding` objects:
```json
{
  "title": "Inconsistent founding year claimed across site pages (2010 vs. 2012)",
  "category": "internal-consistency",
  "severity": "high",
  "status": "confirmed",
  "confidence": "high",
  "impact": "high",
  "evidence": "Observed at https://example.com/ via cross_page_fact_comparison [2026-08-29T17:45:00Z]: Different pages state contradictory founding years: https://example.com/: 2010; https://example.com/about: 2012. (Confidence: high)",
  "source_skill": "freshness-corroboration",
  "fingerprint": "consistency:founding-year-mismatch",
  "suggested_action": {
    "summary": "Unify the company founding year across all web pages and structured data.",
    "priority": "high",
    "how_to_fix": "Identify the authoritative founding date and update all occurrences on the homepage, About page, footer, and Organization JSON-LD."
  }
}
```
Return candidate findings as a JSON array to the orchestrator.
