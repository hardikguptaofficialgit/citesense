# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a website for AI-discoverability and on-site-engagement
problems and produces a structured report of findings and prioritized fixes. Built for Adobe
University Hackathon 2026, Round 3.

## Entrypoint
`skills/audit-orchestrator` receives the audit request and composes the other five skills into
the final report. See `marketplace.json` for the full manifest.

## Skills

| Skill | Concern | What it adds |
|---|---|---|
| **crawl-render-audit** | Off-site discoverability, steps A-C | Is the crawler let in (per AI-agent robots.txt rules, not just `*`)? Can it read the page without executing JS? Is structured data present and valid? Are facts locked inside images/canvas? |
| **freshness-corroboration** | Temporal + internal consistency (Appendix D, half 1) | Is content stale? Does the site contradict itself across pages (e.g. two different founding years)? |
| **engagement-audit** | On-site engagement | Does a visitor understand the page, find a next step, avoid broken links and dead ends, get a usable mobile experience? |
| **citation-simulator** | Proof-of-failure | Actually runs the search-fetch-answer loop a real AI assistant would for realistic questions about the brand, and classifies the result (correct / omitted / misattributed / stale / contradicted) instead of only inferring failure from structural signals. |
| **trust-corroboration-graph** | External identity (Appendix D, half 2) | Do independent third-party sources corroborate the brand's core claims? Can the brand be told apart from other entities sharing its name? |
| **audit-orchestrator** (entrypoint) | Composition | Runs the above in dependency order, merges/deduplicates their findings into the fixed schema, adds proactive beyond-defect recommendations, validates and returns the final report. |

## Why split this way
`crawl-render-audit` establishes ground truth (ideally run first). `freshness-corroboration`
checks the site against *itself*; `trust-corroboration-graph` checks it against the *rest of
the web* -- kept as separate skills because they answer genuinely different questions
(consistency vs. corroboration) even though both stem from Appendix D. `citation-simulator` is
the "did this actually cause a real failure" proof layer, sitting downstream of the others.
`engagement-audit` is the independent on-site half of the problem. `audit-orchestrator` is pure
composition -- it contains no detection logic of its own.

## Report shape
See `skills/audit-orchestrator/references/report-schema.json`. Every finding has `id`, `title`,
`severity`, `evidence`, and `suggested_action` at minimum; the report additionally includes an
optional `proactive_recommendations` array for beyond-defect suggestions.

## Running it
Each data-gathering skill's `scripts/` are deterministic, dependency-free (stdlib only, with an
optional Playwright fallback in crawl-render-audit) Python, runnable directly, e.g.:
```
python3 skills/crawl-render-audit/scripts/crawlability_check.py https://example.com
```
`citation-simulator` and `trust-corroboration-graph` also require the invoking agent's own live
web-search tool for the parts that genuinely can't be scripted deterministically (their bundled
scripts only handle the structured scoring/query-generation layer around that).

## Guardrails
Recommend-only; no skill modifies a live site. Read-only, respects robots.txt, no destructive/
authenticated/rate-abusing actions. Target audit runtime: under 5 minutes for a typical site.

## Evidence and runtime rules

The orchestrator treats each specialist as a bounded producer: HTTP requests time out in 8--12
seconds, samples are capped, and an unavailable page/source is inconclusive rather than a finding.
Deduplicate URLs before fetching. Robots decisions are evaluated per requested path using
longest-match `Allow`/`Disallow` precedence, so partial blocking is not mistaken for a site ban.
Rendered DOM evidence is a finding only where a named core fact/action is absent from raw HTML;
JavaScript alone is not a defect.

JSON-LD checks cover parsing, important fields, Organization identity/sameAs, Product/Offer fields,
canonical alignment, visible-name consistency, and duplicate entity IDs. Citation and trust checks
separate direct site evidence, external corroboration, and inference; a failed external lookup is
never evidence that an AI assistant will not cite a site. Run regressions with
`python -m unittest discover -s tests -v`.
