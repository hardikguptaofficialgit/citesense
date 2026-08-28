---
name: freshness-corroboration
description: Checks whether a site's facts are current and internally self-consistent -- stale copyright/last-updated signals, evergreen-looking award or press claims with no date qualifier, and contradictions between what different pages on the SAME site say (e.g. founding year or phone number disagreeing between the footer and the About page). Use when diagnosing whether outdated or self-contradictory content is undermining a brand's trustworthiness to AI assistants. Does not check external/third-party corroboration -- that is trust-corroboration-graph's job.
---

# Freshness & Internal Consistency Audit (Appendix D, temporal half)

Invoked by `audit-orchestrator` after
`crawl-render-audit`. Scope is deliberately narrow and internal: does the site's own content
agree with itself, and does it look current? It does **not** check whether outside sources
corroborate the brand's claims -- that's `trust-corroboration-graph`.

## Inputs
- `pages`: 3-6 URLs on the same site likely to repeat the same durable facts -- typically the
  homepage footer, an About/Company page, a Contact page, and one or two product/blog pages.

## Procedure
1. Run `scripts/freshness_and_consistency_scan.py <page1> <page2> ...` across the selected
   pages in a single call.
2. Any `founding_year_mismatch` or `phone_number_mismatch` in `cross_page_consistency_issues`
   -> **high**: an inconsistent claim actively signals unreliability, worse than a claim that's
   merely rare.
3. `stale_copyright` with a 2+ year gap -> **low** on its own; escalate to **medium** if the
   page also has no `jsonld_dates`, `article_modified_time_meta`, or
   `visible_last_updated_text` at all -- there's no freshness signal for a machine to check
   currency against.
4. `award_mention_candidates` are heuristic leads -- confirm by reading the surrounding content.
   A past-dated achievement presented as if current, with no date qualifier -> **low**.
5. Do not report a mismatch or staleness signal you haven't directly confirmed.

## Output
JSON array of finding objects, e.g.:
```json
{
  "title": "Founding year is inconsistent across site (2010 vs. 2012)",
  "category": "internal-consistency",
  "severity": "high",
  "evidence": "Homepage footer states 'Founded in 2010'; /about states 'Since 2012, Acme has served customers.'",
  "source_skill": "freshness-corroboration",
  "suggested_action": {
    "summary": "Pick the correct founding year and update every page (and any Organization JSON-LD foundingDate field) to match.",
    "priority": "high",
    "how_to_fix": "Verify the actual founding date from company records, then find-and-replace the wrong year across footer, About page, and structured data."
  }
}
```
Return findings as a JSON array to the orchestrator.
