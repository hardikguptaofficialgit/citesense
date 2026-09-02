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
    Snapshots --> Skill4[trust-corroboration-graph]
    Snapshots --> Skill5[citation-simulator]
    
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
| **citation-simulator** | Proof-of-failure | Runs the search-fetch-answer loop for realistic questions about the brand, and classifies the result (correct / omission / misattribution / staleness / contradiction). |
| **trust-corroboration-graph** | External identity (Appendix D, half 2) | Do independent third-party sources corroborate the brand's core claims? Can the brand be told apart from other entities sharing its name using Schema.org `sameAs` disambiguation? |
| **audit-orchestrator** (entrypoint) | Composition & Orchestration | Crawls pages once via `SiteInventory`, executes specialist skills to collect `CandidateFindings`, merges and deduplicates by root cause, prioritizes by severity and impact, adds proactive recommendations, and validates the report. |

---

## Key Features & Improvements

1. **Shared SiteInventory:** Pages are crawled once in a bounded, parallelized pass (default 4-6 pages: root, money page, content page, docs/about page). All 5 specialist skills consume the exact same cached snapshots, eliminating redundant network calls and ensuring consistency.
2. **Structured CandidateFindings Contract:** Every specialist skill generates standardized `CandidateFinding` objects directly with concrete evidence and suggested fixes. The orchestrator never invents or hardcodes findings.
3. **Evidence-Verification Layer:** Every finding includes URL, observation, method, timestamp, and confidence rating (`Observed at <url> via <method> [<timestamp>]: <observation> (Confidence: <confidence>)`).
4. **Finding Metadata:** Includes `status` (`confirmed` / `likely-risk` / `proactive`), `confidence` (`high` / `medium` / `low`), and `impact` (`critical` / `high` / `medium` / `low`).
5. **False-Positive Elimination:**
   - Follows HTTP redirects up to 5 hops; links redirecting to 200 are recognized as working.
   - 4xx/5xx responses are distinguished from transient network timeouts.
   - Missing `dateModified` or `datePublished` on static pages is **not** penalized.
   - Breadcrumbs are only evaluated on deep paths (`depth >= 2`), not on root/shallow pages.
   - JavaScript usage alone is **not** a defect if raw HTML contains the core facts.
   - Entity collisions are only flagged if plausible in the same/adjacent industry without `sameAs` disambiguation.
6. **Fact-Extractability Detection:** Analyzes raw HTML vs rendered DOM for crucial facts (pricing, contact, products, policies) and identifies facts trapped inside `<canvas>` or images without alt text.
7. **Advanced Engagement Detection:** Recognizes `<button>`, `<input type="submit">`, `<form>`, `role="button"`, and prominent CTA links.
8. **Root-Cause Deduplication:** Consolidates findings sharing the same fingerprint across pages and skills, merging evidence and assigning highest severity.
9. **Strict Guardrails:** Recommend-only, 100% read-only, respects robots.txt, strictly budgeted under 5 minutes (typical audit runs in 5-20 seconds).
10. **Report Schema Compliance:** Fully conforms to `skills/audit-orchestrator/references/report-schema.json`.
11. **HTML Report Dashboard:** Renders `report.json` into a single self-contained HTML file (inline CSS/JS, zero external requests, no build step) with a severity summary, a discoverability-vs-engagement split, collapsible evidence, and a visually distinct proactive-recommendations section.
12. **Auto-Generated Fix Snippets:** Structured-data findings carry a ready-to-paste JSON-LD block pre-populated from observed ground truth. Unknown values are explicit `REPLACE_WITH_...` markers, and a snippet that would be mostly placeholders is **suppressed** rather than shipped as a fix.
13. **Report Comparison:** Diffs two reports by stable `fingerprint` into `resolved` / `new` / `unchanged` buckets with a weighted `score_delta`, so "did the fix work?" is answerable.
14. **AI-Citability Score:** A deterministic, monotonic 0-100 score in `summary.citability_score`, with its formula and rationale documented in `references/citability-score.md` rather than hidden in code.

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

# 5. Report Merge & Validation
python skills/audit-orchestrator/scripts/compose_report.py validate --input report.json

# 6. HTML Report Dashboard
#    Renders report.json into ONE self-contained HTML file (inline CSS/JS, no external
#    requests, no build step). Omit --output to write to stdout.
python skills/audit-orchestrator/scripts/render_dashboard.py report.json --output dashboard.html

# 7. Report Comparison / Diff (before vs. after a fix, or two points in time)
#    Matches findings by fingerprint (falling back to normalized title + category) and
#    buckets them into resolved / new / unchanged, with a weighted score_delta.
python skills/audit-orchestrator/scripts/compare_reports.py before.json after.json --output diff.json

# 8. AI-Citability Score (recompute + show the arithmetic for any existing report)
python skills/audit-orchestrator/scripts/scored.py report.json --explain

# 9. Fix-Snippet Inspector
#    Shows, per structured-data finding, whether a JSON-LD snippet could be generated and
#    WHY NOT when it could not. Needs --inventory: report.json alone carries no ground
#    truth, and this tool will not fabricate one.
python skills/audit-orchestrator/scripts/fix_snippets.py report.json \
    --inventory inventory.json --output annotated-report.json
```

All four report-consuming CLIs fail readably rather than with a traceback — a missing file,
malformed JSON, or a non-object JSON document produces a one-line `error:` on stderr and
exit code 1 — and `--output` creates its parent directory if it does not exist.

### What shows up inside the report
Two additive fields are produced automatically during composition. Both are **optional** in
`references/report-schema.json` — existing consumers are unaffected.

**`summary.citability_score`** — a 0-100 AI-Citability Score written on every composed
report (`run_audit.py` and `compose_report.py merge`). Starts at 100 and subtracts a
per-finding severity penalty (critical 25 / high 12 / medium 5 / low 2), with a small,
data-gated corroboration credit. The exact formula, worked example, and rationale live in
[`skills/audit-orchestrator/references/citability-score.md`](skills/audit-orchestrator/references/citability-score.md).

```json
"summary": { "total_findings": 7, "critical": 0, "high": 1, "citability_score": 64 }
```

**`suggested_action.fix_snippet`** — a ready-to-paste JSON-LD block on structured-data
findings, pre-populated from data the crawl actually observed (brand name, `sameAs`,
founding year, page H1, real URL path). It appears only when the audit holds enough real
data to fill the entity's identifying fields; genuinely unknown values are emitted as
explicit `REPLACE_WITH_...` markers, and a snippet that would be mostly placeholders is
suppressed rather than presented as a fix.

```json
"suggested_action": {
  "summary": "Add Organization JSON-LD markup to the homepage.",
  "priority": "medium",
  "how_to_fix": "Add a JSON-LD script declaring @type 'Organization'...",
  "fix_snippet": "<script type=\"application/ld+json\">\n{\n  \"@type\": \"Organization\",\n  \"name\": \"Mozilla\",\n  \"foundingDate\": \"1998\",\n  \"logo\": \"REPLACE_WITH_YOUR_LOGO_URL\"\n}\n</script>"
}
```

Snippets need the crawl's ground truth. `run_audit.py` supplies it automatically; when
merging findings by hand, pass a saved inventory (or a bare `ground_truth` JSON):

```bash
python skills/audit-orchestrator/scripts/run_audit.py https://example.com \
    --save-inventory inventory.json --output report.json

python skills/audit-orchestrator/scripts/compose_report.py merge \
    --site https://example.com --input crawl_findings.json engagement_findings.json \
    --inventory inventory.json --output report.json
```

---

## Running Tests

Run the complete unit and adversarial test suite:
```bash
python -m unittest discover -s tests -v
```
All tests run with Python standard library with zero external dependencies.
