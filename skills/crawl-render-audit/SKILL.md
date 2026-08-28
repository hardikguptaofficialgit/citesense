---
name: crawl-render-audit
description: Audits a website's off-site discoverability pipeline -- whether AI crawlers are let in, whether the page's content is readable without executing JavaScript, whether structured data (JSON-LD/schema.org) is present and valid, and whether key facts are locked inside non-textual elements (images/canvas). Use when diagnosing why a brand's pages don't get crawled, read, or cited correctly by AI assistants.
---

# Crawl & Render Audit (discoverability: steps A-C)

Invoked by `audit-orchestrator` first, since its structured-data extraction feeds ground truth. Answers the first
three questions from the appendix's discoverability model, in order:
1. Is the crawler let in? (robots.txt for AI-specific user agents, not just `*`)
2. Can it read what's on the page? (raw HTML vs. rendered DOM; structured data)
3. Can it pick out the specific fact? (facts locked inside images/canvas vs. plain text)

A page can pass step 1 and still fail step 2 or 3 -- always run all checks.

## Inputs
- `site_url`: the root domain to audit (e.g. `https://example.com`)
- `sample_pages` (optional): representative page URLs to deep-scan beyond the homepage --
  ideally one money page (product/pricing/service) and one content page (article/FAQ). If not
  provided, discover 2-3 candidates from the homepage's internal links or the sitemap found in
  step 1.

## Procedure
1. **Crawlability.** Run `scripts/crawlability_check.py <site_url>`.
   - Evaluate each audited path with longest-match `Allow`/`Disallow` semantics. Report only an
     important path actually denied; distinguish partial from site-wide denial. Evidence includes rule, agent, and path.
   - Missing sitemap.xml -> **medium**.
   - llms.txt found -> not a finding, note as an existing strength for the orchestrator.
2. **Render & data scan.** For the homepage and each sample page, run
   `scripts/render_and_data_scan.py <page_url>`.
   - JS use is not a defect. Report a render gap only when an identified core fact/action is
     absent from raw HTML and present only in rendered DOM; an unavailable renderer is inconclusive.
   - No JSON-LD on a money page -> **high**. JSON-LD present but missing required fields ->
     **medium**.
   - Missing title/meta description -> **medium**. Missing canonical on a site with duplicate
     or parameterized URLs -> **medium**. Missing viewport meta -> **low** here (also relevant
     to `engagement-audit` -- don't duplicate the finding, just note it happened on both).
   - `media_locked_fact_candidates` are heuristic leads only -- confirm each one against the
     page's actual visible content before reporting it as a finding.
3. **Extract ground truth** for the other skills as you go: brand name, category, JSON-LD
   Organization/Product fields, and 3-5 core factual claims (founding year, HQ, flagship
   offering). Pass this forward as `ground_truth` to `citation-simulator` and
   `trust-corroboration-graph` via the orchestrator.
4. Only report issues you actually confirmed -- false positives are explicitly penalized.

## Output
JSON array of finding objects, e.g.:
```json
{
  "title": "GPTBot explicitly disallowed while wildcard robots rule allows all",
  "category": "crawlability",
  "severity": "critical",
  "evidence": "robots.txt at https://example.com/robots.txt: 'User-agent: GPTBot / Disallow: /', while 'User-agent: *' has no blocking Disallow.",
  "source_skill": "crawl-render-audit",
  "suggested_action": {
    "summary": "Remove or narrow the GPTBot-specific Disallow rule.",
    "priority": "critical",
    "how_to_fix": "Edit robots.txt: delete the GPTBot block, or replace 'Disallow: /' with only the specific paths that should stay private."
  }
}
```
Return findings as a JSON array to the orchestrator. Do not compute the report's `summary`
yourself -- that's `compose_report.py`'s job once all skills report in.
