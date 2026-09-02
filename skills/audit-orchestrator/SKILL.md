---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Given a website, runs crawl-render-audit, freshness-corroboration, engagement-audit, trust-corroboration-graph, and citation-simulator using a shared single-pass SiteInventory, merges CandidateFindings into the fixed audit-report schema, adds cross-cutting proactive recommendations, and emits the final report. Use this skill to receive an audit request for a site and produce the complete report -- it composes the other five skills rather than duplicating their checks.
---

# Audit Orchestrator (entrypoint)

## Guardrails (apply across the whole run)
- **Recommend-only.** Never modify the live site. Everything is read-only.
- **Respect robots.txt.** `crawl-render-audit`'s first step evaluates which paths/agents are disallowed -- when fetching pages on the same site beyond the homepage/robots.txt/sitemap.xml, respect robots.txt disallow rules for AI user agents.
- **No destructive, authenticated-area, or rate-abusing actions.**
- **Runtime budget.** Target under 5 minutes total for a typical site (typically 10-30 seconds). Bounded page crawling (4-6 pages max), cap broken-link sampling at 8 links.
- **Shared SiteInventory.** Pages are crawled once and cached in `SiteInventory`, eliminating redundant HTTP requests across skills.

## Procedure
1. **Input:** a `site_url`.
2. **Execute Single-Pass Crawl & Audit:**
   ```bash
   python3 skills/audit-orchestrator/scripts/run_audit.py <site_url> --output report.json
   ```
   Or run each specialist skill using the shared inventory:
   - `crawl-render-audit`: Evaluates robots.txt, sitemaps, JSON-LD schema, and fact extractability.
   - `freshness-corroboration`: Evaluates claim-based freshness and cross-page factual consistency (missing dateModified is not a defect).
   - `engagement-audit`: Evaluates orientation, buttons/forms/CTAs, navigation, and mobile responsiveness.
   - `citation-simulator`: Evaluates simulated search loop for omissions, misattributions, staleness, and contradictions.
   - `trust-corroboration-graph`: Evaluates external corroboration and entity disambiguation risk.
3. **Structured CandidateFindings Contract:**
   Every skill returns structured `CandidateFinding` objects with:
   - `title`, `category`, `severity`, `status` (`confirmed`/`likely-risk`/`proactive`), `confidence`, `impact`.
   - Verifiable `evidence` containing URL, observation, method, timestamp, and confidence.
   - Stable `fingerprint` for root-cause deduplication.
   - `suggested_action` (`summary`, `priority`, `how_to_fix`).
4. **Proactive Recommendations:**
   Review what was learned across all skills and generate 2-4 proactive, beyond-defect suggestions (e.g. adding FAQPage schema or llms.txt protocol).
5. **Merge & Deduplicate:**
   Findings sharing the same root cause are deduplicated, their evidence is consolidated, and the highest severity and impact are assigned. Sequential `F-001`, `F-002`, ... IDs are assigned.
6. **Validate:**
   ```bash
   python3 skills/audit-orchestrator/scripts/compose_report.py validate --input report.json
   ```
7. Return `report.json` as the final audit report.

## Post-report tooling (all stdlib, all optional)
- **Fix snippets & score (automatic).** Composition attaches a ready-to-paste JSON-LD
  `suggested_action.fix_snippet` to structured-data findings wherever observed ground truth
  is rich enough to populate them, and writes a 0-100 `summary.citability_score`. Both are
  additive optional schema fields. Formula and rationale: `references/citability-score.md`.
- **Dashboard.** `python3 scripts/render_dashboard.py report.json --output dashboard.html`
  renders a single self-contained HTML view (no external requests, no build step).
- **Diff two runs.** `python3 scripts/compare_reports.py before.json after.json --output diff.json`
  buckets findings into resolved / new / unchanged by `fingerprint` and reports a weighted
  `score_delta`.

## Output
The final report strictly matches `references/report-schema.json`: `site`, `audited_at`, `summary` (counts by severity plus discoverability/engagement split), `findings` (each with `id`, `title`, `severity`, `evidence`, `suggested_action`), and an additive `proactive_recommendations` array.
