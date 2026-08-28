---
name: trust-corroboration-graph
description: Checks whether independent third-party sources (not controlled by the brand) corroborate its core factual claims, and whether the brand can be reliably told apart from other entities that share its name. Use when diagnosing why an AI assistant might distrust, omit, or misattribute facts about a brand due to weak external corroboration or name-collision confusion -- the identity half of Appendix D, distinct from freshness-corroboration's internal-consistency checks.
---

# Trust & Corroboration Graph (Appendix D, identity half)

Invoked by `audit-orchestrator`. External-facing: looks at what the rest of the web says about
the brand, not what the brand says about itself. Identity counterpart to
`freshness-corroboration`, which only checks the brand's own pages against each other.

## Inputs
- `brand_name`, `category`, `location` (from ground truth)
- `core_claims`: 3-5 of the brand's most important checkable claims (founding year, HQ,
  flagship product/service, notable certification/affiliation) -- pull from
  `crawl-render-audit`'s structured-data extraction where possible.

## Procedure
1. **Corroboration pass.** For each core claim, search for independent confirmation --
   Wikipedia/Wikidata, LinkedIn company page, industry directories, press coverage, review
   platforms. Record `{domain, is_brand_owned, supports_fact}` per source found
   (`is_brand_owned` = true only for the brand's own site/verified social profiles it directly
   controls; third-party marketplace listings the brand merely populated still count as
   independent, since an outside system chose to host them).
2. Run `scripts/corroboration_scorer.py '<json of facts + sources>'` for a
   `corroboration_strength` rating per fact (`strong`/`weak`/`contested`/`contradicted`/
   `uncorroborated`).
3. **Entity-collision pass.** While searching, note other real entities sharing the brand's
   name (or a close variant) in the same or an adjacent space where confusion is plausible --
   ignore coincidental matches with zero practical confusion risk. Check the brand's own site
   for disambiguating markers: `sameAs` links, `alternateName`, geo/industry qualifiers in its
   Organization schema.
4. Run the same script with `name_collisions_found` and `disambiguating_markers_present` for a
   `risk` rating.
5. Convert to findings:
   - `uncorroborated`/`contradicted` on a core identity or transactional claim -> **high**; on
     a secondary claim -> **medium**.
   - `contested` (independent sources disagree with each other) -> **high** regardless of claim.
   - Entity-collision `risk: high` -> **critical** if the colliding entity is in the same or an
     adjacent industry; **high** otherwise. `risk: medium` -> **medium**.
6. Do not report a collision or corroboration gap you didn't actually verify via a real search
   in this run.

## Output
```json
{
  "title": "No independent corroboration found for founding year claim",
  "category": "corroboration",
  "severity": "medium",
  "evidence": "Searched for independent confirmation of 'founded in 2010'; found no mention on Wikipedia, LinkedIn, or press coverage. Only source is the brand's own About page.",
  "source_skill": "trust-corroboration-graph",
  "suggested_action": {
    "summary": "Get the founding date recorded on at least one independent, authoritative source.",
    "priority": "medium",
    "how_to_fix": "Add/verify the fact on LinkedIn and Crunchbase profiles, and link any past press coverage from an About/Press page."
  }
}
```
Return findings as a JSON array to the orchestrator.
