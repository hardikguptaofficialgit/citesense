---
name: engagement-audit
description: Audits on-site engagement -- whether a visitor who arrives understands what the page is for, can find a clear next step, doesn't hit broken links or dead ends, gets a usable mobile experience, and whether the site shows any capacity to use context about a returning or logged-in visitor. Uses button/form/CTA detection, page purpose classification, and redirect-aware link validation.
---

# Engagement Audit (on-site half)

Invoked by `audit-orchestrator` to audit what happens after click-through. Even a perfectly discoverable brand will lose visitors if arriving pages lack clear orientation, prominent next steps, or working navigation.

## Inputs
- `inventory`: a loaded `SiteInventory` object or target page URL.

## Procedure
1. Run `python3 skills/engagement-audit/scripts/engagement_scan.py <inventory_json_or_url> --findings-only`.
2. **Orientation:**
   - Missing `<h1>` heading -> **high**. Multiple competing `<h1>` tags -> **low**.
   - Page purpose alignment with primary title and heading.
3. **Navigation & Next-Step Actions:**
   - Evaluates `<button>`, `<form>`, `<input type="submit">`, `role="button"`, and CTA links.
   - Commercial or homepage with 0 actionable next steps -> **high**.
   - Dead-end page (< 2 internal links on content/product page) -> **medium**.
   - Deep hierarchical pages lacking breadcrumbs -> **low** (shallow/root pages are explicitly exempt).
4. **Redirect-Aware Broken Links:**
   - Checks sampled internal links, following HTTP redirects.
   - Redirects to 200 are **not** broken; only confirmed 4xx/5xx errors are flagged -> **medium**.
5. **Mobile Readiness:**
   - Missing viewport meta tag -> **high**.

## Output
JSON array of structured `CandidateFinding` objects:
```json
{
  "title": "Commercial landing page lacks clear call-to-action buttons or interactive forms",
  "category": "navigation",
  "severity": "high",
  "status": "confirmed",
  "confidence": "high",
  "impact": "high",
  "evidence": "Observed at https://example.com/ via interactive_element_analysis [2026-08-29T17:45:00Z]: Page classified as 'product_pricing' contains 0 CTA buttons, 0 interactive forms, and 0 action links. (Confidence: high)",
  "source_skill": "engagement-audit",
  "fingerprint": "engagement:missing-cta:/pricing",
  "suggested_action": {
    "summary": "Add prominent primary call-to-action (CTA) buttons.",
    "priority": "high",
    "how_to_fix": "Add visually distinct CTA buttons (e.g. 'Get Started', 'View Pricing', 'Contact Sales') above and below the fold."
  }
}
```
Return candidate findings as a JSON array to the orchestrator.
