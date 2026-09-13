# Benchmark Bugs Found

## BUG-001: Missing-sitemap finding emitted for unreadable sites

- **Reproduction:** Run the 1,000-site benchmark against a public domain whose
  homepage and sitemap probes are network failures. For example, `miwifi.com`
  produced zero readable pages but received `crawl:missing-xml-sitemap` with
  `status: confirmed`.
- **Affected scope:** 170 benchmark receipts in the first run had zero readable
  pages and this confirmed sitemap finding.
- **Root cause:** `evaluate_crawlability()` inferred that a sitemap was absent
  when sitemap and robots requests were unavailable. It did not gate the
  absence check on at least one readable page.
- **Expected behavior:** An unreadable/access-limited crawl must not turn failed
  probes into a confirmed semantic or discoverability defect.
- **Actual behavior:** A missing-sitemap finding was emitted and penalized the
  score for sites that CiteSense could not read.
- **Fix applied:** Suppress the absence-of-sitemap finding when the inventory
  has zero readable pages. The normal finding remains enabled when at least one
  page is readable.
- **Regression coverage:** Added
  `test_unreadable_crawl_does_not_infer_missing_sitemap`.
- **Verification:** Reran all 170 affected receipts. The corrected benchmark
  contains zero unreadable sites with `crawl:missing-xml-sitemap`.
