# CiteSense 1,000-Site Generalization Report

Generated: 2026-09-13T17:25:17.219891+00:00

## Executive summary
- Sites attempted/completed: 1000/1000
- Accessible: 669; total findings: 4180
- Broken evidence references: 0
- Final verdict: **NEEDS INVESTIGATION**

## Dataset composition
The dataset combines conservative curated seeds and the latest standard Tranco list. Unknown categories remain explicitly labelled `unknown`; no category is inferred from a domain name.

## Access statistics
```json
{
  "readable": 669,
  "anti-bot": 119,
  "network failure": 162,
  "robots-blocked": 45,
  "login/auth-limited": 5
}
```

## Score distribution
```json
{
  "count": 731,
  "mean": 74.59,
  "median": 79.0,
  "p25": 64.5,
  "p75": 87.0,
  "minimum": 6.0,
  "maximum": 100.0
}
```

## Category results
See `benchmark_category_results.csv`. Findings are observations of CiteSense behavior, not AI citation accuracy.

## Page-purpose classification
```json
{
  "article_docs": 434,
  "contact_support": 409,
  "general": 269,
  "homepage": 631,
  "html_fragment": 23,
  "product_landing": 339,
  "product_pricing": 188,
  "unknown": 261
}
```

## Non-commercial Product/Offer candidates
Count requiring contextual review: 55. These are not automatically labelled false positives; several are legitimate billing, pricing, or commercial subpaths on otherwise non-commercial domains.

## False-positive and evidence analysis
The runner checks evidence references against the report evidence ledger. Access-limited sites are not treated as semantic failures, and no external search or AI citation claim is made.
Access-limited semantic findings: 0.

## Resource and page-purpose analysis
See `resource_classification_results.json` and per-site inventory summaries in `results/`.

## Root-cause deduplication
The production report exposes deduplicated fingerprints and score penalties. `root_causes` records reported occurrences and the production deduplicated penalty; raw pre-dedup candidate counts are not exposed by the production contract, so this benchmark does not invent them.

## Performance
```json
{
  "mean_seconds": 23.643,
  "median_seconds": 17.206,
  "p95_seconds": 48.937,
  "p99_seconds": 96.832,
  "maximum_seconds": 1356.025
}
```
Typical and P95 audits remained below five minutes. The maximum outlier is called out rather than hidden; investigate it before claiming universal under-five-minute performance.

## Top findings
- Missing Schema.org Organization structured data on root landing page — 462 occurrence(s), 69.06% of accessible sites
- No site search affordance found on any crawled page — 374 occurrence(s), 55.9% of accessible sites
- Brand identity is not anchored to any independent authority source — 303 occurrence(s), 45.29% of accessible sites
- Missing primary H1 heading on landing page — 297 occurrence(s), 44.39% of accessible sites
- No returning-visitor or account affordance detected — 263 occurrence(s), 39.31% of accessible sites
- Deep hierarchical page lacks breadcrumb navigation trail — 256 occurrence(s), 38.27% of accessible sites
- Missing Schema.org Product and Offer structured data on commercial page — 185 occurrence(s), 27.65% of accessible sites
- Content images carry no text alternative, hiding any fact they display — 170 occurrence(s), 25.41% of accessible sites
- Missing meta description on key landing page — 147 occurrence(s), 21.97% of accessible sites
- Missing XML sitemap declared in robots.txt or available at /sitemap.xml — 110 occurrence(s), 16.44% of accessible sites

## Security/access behavior
The production engine was run with its existing robots enforcement, SSRF checks, redirect validation, response-size limits, and no-bypass behavior. Only BUG-001 received a minimal evidence-bound fix.

## Unexpected patterns
- 619 sites were conservatively labelled unknown rather than guessed.
- 1356.025 seconds was the slowest audit; median was 17.206 seconds.
- 55 non-commercial Product/Offer candidates require contextual review; they are not automatically false positives.

## Genuine bugs discovered
BUG-001 was discovered and fixed: unreadable sites could receive a confirmed missing-sitemap finding. The affected 170 receipts were rerun; zero unreadable sites now receive that finding. See `BUGS_FOUND.md`.

## Production changes made
One minimal evidence-bound fix was made for BUG-001. No benchmark-specific production mode or domain-specific exception was added.

## Interpretation
This experiment measures CiteSense behavior across diverse public websites. It does not measure what percentage of websites are cited by AI systems and does not establish AI citation accuracy.

## Final generalization verdict: **NEEDS INVESTIGATION**
