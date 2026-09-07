---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Given a website, runs crawl-render-audit, freshness-corroboration, engagement-audit, trust-corroboration-graph, and citation-simulator using a shared single-pass SiteInventory, merges CandidateFindings into the fixed audit-report schema, adds cross-cutting proactive recommendations, and emits the final report. Use this skill to receive an audit request for a site and produce the complete report -- it composes the other five skills rather than duplicating their checks.
license: MIT
allowed-tools: Bash, Read, Write
---

# Audit Orchestrator (entrypoint)

## Guardrails (apply across the whole run)
- **Recommend-only.** Never modify the live site. Everything is read-only.
- **robots.txt is enforced, not just parsed.** Every fetch goes through `SiteInventory.may_fetch()`, which resolves the path against the `*` group and refuses disallowed URLs; declined URLs are recorded in `skipped_by_robots`. This gates page crawling and the broken-link sampler alike.
- **No destructive, authenticated-area, or rate-abusing actions.**
- **Runtime budget.** Target under 5 minutes total; a typical site completes in 2-20 seconds. Bounded page crawling (5 pages by default), broken-link sampling capped at 8 links.
- **Never assert an observation that was not made.** Checks requiring live third-party search are exposed through the specialist skills' standalone CLIs for agent-driven runs; the deterministic pipeline does not simulate them. See `references/adding-checks.md`.
- **Shared SiteInventory.** Pages are crawled once and cached in `SiteInventory`, eliminating redundant HTTP requests across skills.

## Procedure
1. **Input:** a `site_url`.
2. **Execute Single-Pass Crawl & Audit:**
   ```bash
   python3 skills/audit-orchestrator/scripts/run_audit.py <site_url> --output report.json
   ```
   Or run each specialist skill using the shared inventory:
   - `crawl-render-audit`: Evaluates robots.txt (scored by crawler class -- blocking training crawlers costs no citations, blocking search-index or user-triggered agents does), sitemaps, JSON-LD schema, and facts locked in images.
   - `freshness-corroboration`: Evaluates claim-based freshness and cross-page factual consistency (missing dateModified is not a defect).
   - `engagement-audit`: Evaluates orientation, buttons/forms/CTAs, navigation, mobile responsiveness, and the cold-arrival case -- a visitor landing mid-site from an AI citation with no homepage context.
   - `citation-simulator`: Tests answerability -- given only the pages a retrieval bot fetched, could an assistant quote an answer about identity, offering, pricing or contact? (Its live-search classification mode is agent-supplied; see that skill.)
   - `trust-corroboration-graph`: Checks whether any machine-readable path exists from the site to an independent authority (`sameAs` URIs, outbound links to Wikidata/Wikipedia/Crunchbase/LinkedIn/registries). (Its third-party corroboration scoring is agent-supplied; see that skill.)
3. **Structured CandidateFindings Contract:**
   Every skill returns structured `CandidateFinding` objects with:
   - `title`, `category`, `severity`, `status` (`confirmed`/`likely-risk`/`proactive`), `confidence`, `impact`.
   - Verifiable `evidence` containing URL, observation, method, timestamp, and confidence.
   - Stable `fingerprint` for root-cause deduplication.
   - `suggested_action` (`summary`, `priority`, `how_to_fix`).
4. **Proactive Recommendations:**
   `proactive_recommendations.py` derives up to 6 beyond-defect suggestions from what the crawl observed, ordered strongest-evidence-first: FAQPage markup for existing Q&A content, third-party entity anchoring, answer-first content structure, Article schema, WebSite/SearchAction, BreadcrumbList, explicit AI usage terms in robots.txt, an agent-facing NLWeb/MCP endpoint, and llms.txt reported with its real (weak) evidence base. Each fires only on an observed condition, so a well-optimised site correctly receives fewer. Evidence basis: `references/ai-visibility-standards-2026.md`.
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

## References
- `references/report-schema.json` -- the output contract.
- `references/ai-visibility-standards-2026.md` -- what drives AI visibility, with sources, and how each finding and recommendation traces back to it.
- `references/adding-checks.md` -- house rules for adding detection logic without creating false positives.

## Output
The final report strictly matches `references/report-schema.json`: `site`, `audited_at`, `summary` (counts by severity plus discoverability/engagement split), `findings` (each with `id`, `title`, `severity`, `evidence`, `suggested_action`), and an additive `proactive_recommendations` array.
