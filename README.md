# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a website for AI-discoverability and on-site-engagement
problems and produces a structured report of findings and prioritized fixes. Built for Adobe
University Hackathon 2026, Round 3.

## Entrypoint
`skills/audit-orchestrator` is the single entrypoint that orchestrates the audit.
See `marketplace.json` for the full marketplace manifest.

## Architecture & Skills

```mermaid
graph TD
    User([Audit Request: URL]) --> Orchestrator[skills/audit-orchestrator]
    Orchestrator --> SiteInventory[Shared SiteInventory Crawler]
    SiteInventory -->|Single Bounded Crawl| Snapshots[(Cached Page Snapshots & Ground Truth)]
    
    Snapshots --> Skill1[crawl-render-audit]
    Snapshots --> Skill2[freshness-corroboration]
    Snapshots --> Skill3[engagement-audit]
    Snapshots --> Orchestrator2[Orchestrator derives ground truth]
    Orchestrator2 --> Skill4[trust-corroboration-graph]
    Orchestrator2 --> Skill5[citation-simulator]
    
    Skill1 -->|CandidateFindings + Evidence| Dedup[Root-Cause Deduplication & Impact Prioritization]
    Skill2 -->|CandidateFindings + Evidence| Dedup
    Skill3 -->|CandidateFindings + Evidence| Dedup
    Skill4 -->|CandidateFindings + Evidence| Dedup
    Skill5 -->|CandidateFindings + Evidence| Dedup
    
    Dedup --> Validator[Schema Validator & ID Assigner]
    Validator --> FinalReport[report.json]
```

| Skill | Concern | What it adds |
|---|---|---|
| **crawl-render-audit** | Off-site discoverability, steps A-C | Is the crawler let in (per AI-agent robots.txt rules, not just `*`)? Can it read the page without executing JS? Is structured data present and valid? Are facts locked inside images/canvas? |
| **freshness-corroboration** | Temporal + internal consistency (Appendix D, half 1) | Claim-based freshness: detects actual stale/conflicting facts (e.g. conflicting founding years, expired promotions) instead of treating missing `dateModified` as a defect. |
| **engagement-audit** | On-site engagement | Evaluates orientation, buttons/forms/CTAs, navigation, redirect-aware broken links, and mobile viewport. |
| **citation-simulator** | Proof-of-failure | Generates realistic questions about the brand, then tests **answerability**: given only the pages a retrieval bot actually fetched, could an assistant quote an answer? Also classifies supplied live-search results (omission / misattribution / staleness / contradiction) when an agent provides them. |
| **trust-corroboration-graph** | External identity (Appendix D, half 2) | Observable on-site: does any machine-readable path exist from the brand to an independent authority (`sameAs` URIs, outbound links to Wikidata/Wikipedia/Crunchbase/LinkedIn/registries)? Agent-supplied: scores real third-party corroboration and same-name collision risk. |
| **audit-orchestrator** (entrypoint) | Composition & Orchestration | Crawls pages once via `SiteInventory`, executes specialist skills to collect `CandidateFindings`, merges and deduplicates by root cause, prioritizes by severity and impact, adds proactive recommendations, and validates the report. |

---

## Key Features & Improvements

1. **Shared SiteInventory:** Pages are crawled once in a bounded sequential pass (default 5 pages: root, money page, content page, docs/about page), gated by robots.txt. `crawl-render-audit`, `freshness-corroboration` and `engagement-audit` read the exact same cached snapshots, eliminating redundant network calls. `citation-simulator` and `trust-corroboration-graph` derive their inputs from those same snapshots via the orchestrator.
2. **Structured CandidateFindings Contract:** Every specialist skill generates standardized `CandidateFinding` objects directly with concrete evidence and suggested fixes. The orchestrator never invents or hardcodes findings, and no check claims an observation it did not make -- checks that would require live third-party search are exposed through the standalone skill CLIs for agent-driven runs, not simulated in the deterministic pipeline.
3. **Evidence-Verification Layer:** Every finding includes URL, observation, method, timestamp, and confidence rating (`Observed at <url> via <method> [<timestamp>]: <observation> (Confidence: <confidence>)`).
4. **Finding Metadata:** Includes `status` (`confirmed` / `likely-risk` / `proactive`), `confidence` (`high` / `medium` / `low`), and `impact` (`critical` / `high` / `medium` / `low`).
5. **False-Positive Elimination:**
   - Follows HTTP redirects up to 5 hops; links redirecting to 200 are recognized as working.
   - 4xx/5xx responses are distinguished from transient network timeouts.
   - Missing `dateModified` or `datePublished` on static pages is **not** penalized.
   - Breadcrumbs are only evaluated on deep paths (`depth >= 2`), not on root/shallow pages.
   - JavaScript usage alone is **not** a defect if raw HTML contains the core facts.
   - Entity collisions are only flagged if plausible in the same/adjacent industry without `sameAs` disambiguation.
6. **Fact-Extractability Detection:** Analyzes the **raw, non-JS-executed HTML** for crucial facts (identity, offering, pricing, contact) -- exactly what a non-rendering retrieval bot sees -- and flags pages whose facts are absent from it or locked inside `<canvas>`. No headless browser is used: the audit is deliberately static, which is the harsher and more realistic case for AI crawlers.
7. **Advanced Engagement Detection:** Recognizes `<button>`, `<input type="submit">`, `<form>`, `role="button"`, and prominent CTA links.
8. **Root-Cause Deduplication:** Consolidates findings sharing the same fingerprint across pages and skills, merging evidence and assigning highest severity.
9. **Strict Guardrails:** Recommend-only, 100% read-only, and robots.txt is **enforced on our own fetches** (`SiteInventory.may_fetch()` gates both page crawling and link probing against the `*` group; declined URLs are recorded in `skipped_by_robots`). Strictly budgeted under 5 minutes -- a typical audit runs in 2-7 seconds.
10. **Report Schema Compliance:** Fully conforms to `skills/audit-orchestrator/references/report-schema.json`.

---

## Running the Audit

### 1. End-to-End Orchestrator CLI
To run a complete audit against any website:
```bash
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --output report.json
```

### 2. Standalone Skill CLI
Each specialist script can also be executed independently:
```bash
# 1. Crawlability & Robots Audit
python skills/crawl-render-audit/scripts/crawlability_check.py https://example.com

# 2. Render & Schema Scan
python skills/crawl-render-audit/scripts/render_and_data_scan.py https://example.com

# 3. Freshness & Consistency Scan
python skills/freshness-corroboration/scripts/freshness_and_consistency_scan.py https://example.com

# 4. Engagement Audit
python skills/engagement-audit/scripts/engagement_scan.py https://example.com

# 5. Citation answerability (needs a saved inventory)
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --save-inventory inv.json -o report.json
python skills/citation-simulator/scripts/generate_queries.py inv.json

# 6. Trust / corroboration scoring (agent supplies real third-party search results)
python skills/trust-corroboration-graph/scripts/corroboration_scorer.py '{"brand_name":"Acme","site_url":"https://example.com","facts":[],"name_collisions_found":[],"disambiguating_markers_present":{}}' --findings-only

# 7. Report Merge & Validation
python skills/audit-orchestrator/scripts/compose_report.py validate --input report.json
```

---

## Running Tests

Run the complete unit, adversarial and regression suite:
```bash
python -m unittest discover -s tests -v
```
All tests run with the Python standard library and zero external dependencies.

`tests/test_regressions.py` locks in every false positive and guardrail bug that has been fixed
(gzip transport, copyright ranges, founding-claim prose, page-purpose classification, robots.txt
enforcement, evidence honesty, brand-name extraction). If one fails, a regression was
reintroduced -- see `Progress.md` for the original reproduction.

## Validation runs

`validation-runs/` holds reports regenerated from the current pipeline across six sites of
different shapes, plus `RUNS.md` with runtimes and severity counts. All six validate against
`report-schema.json`.

## Project status

`Progress.md` is the working log: what has been fixed, how each fix was verified, and what is
still open. Read it before changing detection logic.
