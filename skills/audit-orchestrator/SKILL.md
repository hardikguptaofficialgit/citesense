---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Given a website, runs crawl-render-audit, freshness-corroboration, engagement-audit, trust-corroboration-graph, and citation-simulator in the right order, merges their findings into the fixed audit-report schema, adds cross-cutting proactive recommendations, and emits the final report. Use this skill to receive an audit request for a site and produce the complete report -- it composes the other five skills rather than duplicating their checks.
---

# Audit Orchestrator (entrypoint)

## Guardrails (apply across the whole run)
- **Recommend-only.** Never modify the live site. Everything is read-only.
- **Respect robots.txt.** `crawl-render-audit`'s first step already determines which paths/
  agents are disallowed -- when any other skill fetches additional pages on the same site
  beyond the homepage/robots.txt/sitemap.xml, skip any path robots.txt disallows for a generic
  user agent, and note the skip rather than fetching anyway.
- **No destructive, authenticated-area, or rate-abusing actions.**
- **Runtime budget.** Target under 5 minutes total for a typical site. Keep sample pages to
  2-4 per skill, cap citation-simulator at ~10 queries, cap broken-link sampling at 8 links.

## Procedure
1. **Input:** a `site_url`.
2. **Run `crawl-render-audit`** first, against the homepage plus 1-2 sample pages (a money
   page and a content page, discovered from homepage links or the sitemap). Collect its
   findings AND its structured-data extraction as `ground_truth` (brand_name, category,
   location, key_facts) for later steps.
3. **Run `freshness-corroboration`** against 3-6 pages likely to repeat durable facts (footer,
   About, Contact, one or two product/blog pages).
4. **Run `engagement-audit`** against the homepage plus 1-2 pages a real visitor would land on
   from a search/citation click.
5. **Run `trust-corroboration-graph`** using `ground_truth` and 3-5 core claims pulled from
   step 2's structured data.
6. **Run `citation-simulator`** using the same `ground_truth`, now that internal consistency
   (step 3) and external corroboration (step 5) give it something to check simulated answers
   against for staleness/contradiction classification.
7. **Write each skill's findings to a JSON file** (a JSON array of finding objects per skill).
   Contract: each producer supplies `title`, `category`, `severity`, direct `evidence`,
   `source_skill`, `suggested_action.summary`, `suggested_action.priority`, and
   `suggested_action.how_to_fix`; it may add a stable `fingerprint` for root-cause dedupe.
8. **Generate proactive recommendations.** Separately from the findings above, review what
   was learned across all five skills and add 2-4 proactive, non-obvious suggestions that
   would strengthen discoverability or engagement even where no explicit defect was found --
   e.g. adding FAQPage schema to already-strong help content, or suggesting a press/citation
   outreach angle suggested by a corroboration gap that wasn't quite severe enough to be a
   finding. Write these as a JSON array of `{title, rationale, suggested_action}` objects.
   These are recommendations, not problems -- don't force them into the findings schema.
9. **Merge.** Run:
   ```
   python3 scripts/compose_report.py merge --site <site_url> \
       --input crawl_findings.json freshness_findings.json engagement_findings.json \
               trust_findings.json citation_findings.json \
       --proactive proactive_recommendations.json \
       --output report.json
   ```
   This assigns sequential `F-NNN` ids, deduplicates findings reported by more than one skill
   (merging their evidence and keeping the higher severity -- this is common and expected when
   a structural gap and its simulated-answer consequence are both flagged), sorts by severity,
   and computes the summary block.
10. **Validate.** Run `python3 scripts/compose_report.py validate --input report.json` and
    confirm `"valid": true` before returning the report.
11. Return `report.json`'s contents as the final audit report.

## Output
The final report matches `references/report-schema.json`: `site`, `audited_at`, `summary`
(counts by severity plus discoverability/engagement split), `findings` (each with `id`,
`title`, `severity`, `evidence`, `suggested_action`), and an additive `proactive_recommendations`
array. This is a floor, not a ceiling -- additional fields are fine, but every submission must
include at least this shape.
