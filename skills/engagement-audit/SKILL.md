---
name: engagement-audit
description: Audits on-site engagement -- whether a visitor who arrives understands what the page is for, can find a clear next step, doesn't hit broken links or dead ends, gets a usable mobile experience, and whether the site shows any capacity to use context about a returning or logged-in visitor. Use when diagnosing why traffic arrives but doesn't convert or stay.
---

# Engagement Audit (on-site half)

Invoked by `audit-orchestrator`. Counterpart to the discoverability skills: even a brand AI
assistants find and cite perfectly can still lose the visitor after the click-through if the
page itself doesn't orient them or give them somewhere to go next.

## Inputs
- `pages`: 2-4 representative URLs -- ideally the homepage plus one or two pages a visitor
  would actually land on from a search/citation click (product page, blog post, service page).

## Procedure
For each page, run `scripts/engagement_scan.py <page_url>` and interpret:

1. **Orientation.** `issue_no_h1` -> **high**. `issue_multiple_h1` -> **low**. If `title` and
   `h1_texts` say substantially different things, the click-through expectation mismatches the
   page content -> **medium**.
2. **Navigation.** `issue_too_few_links` (< 3 internal links) -> **medium**: a dead end by
   construction. No nav landmark and no breadcrumbs together -> **low**.
3. **Next-step signals.** `issue_no_clear_cta` -> **high** on a money page, **medium**
   elsewhere -- a page with no clear next action is the single biggest engagement killer.
4. **Broken links.** Any entries in `broken_link_sample.broken` -> **medium** per distinct
   broken destination (cap at the 3 most important to avoid flooding the report).
5. **Mobile.** No `viewport_meta_present` -> **high**. If `crawl-render-audit` also flagged
   this page for the same reason, merge evidence rather than duplicating the finding.
6. **Personalization readiness.** Absent account/preference signals is normal for most sites
   and should be a **beyond-defect** proactive suggestion, not a problem. Only treat it as a
   genuine finding if the site's own content implies repeat visits matter (subscriptions,
   loyalty programs, multi-session workflows) yet shows no mechanism to pick up where a
   visitor left off.

## Output
JSON array of finding objects, e.g.:
```json
{
  "title": "Product page has no clear call-to-action",
  "category": "navigation",
  "severity": "high",
  "evidence": "https://example.com/products/widget-pro returned 0 CTA-like links; page has 2 internal links total.",
  "source_skill": "engagement-audit",
  "suggested_action": {
    "summary": "Add a single, visually prominent primary action above the fold.",
    "priority": "high",
    "how_to_fix": "Insert a styled CTA button linking to checkout/contact directly below the product description."
  }
}
```
Return findings as a JSON array to the orchestrator.
