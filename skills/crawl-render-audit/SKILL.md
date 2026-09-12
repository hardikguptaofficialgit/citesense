---
name: crawl-render-audit
description: Audits a website's off-site discoverability pipeline -- whether AI crawlers are let in, whether the page's content is readable without executing JavaScript, whether structured data (JSON-LD/schema.org) is present and valid, and whether key facts are locked inside non-textual elements (images/canvas). Use when diagnosing why a brand's pages don't get crawled, read, or cited correctly by AI assistants.
license: MIT
allowed-tools: Bash, Read
---

# Crawl & Render Audit (discoverability: steps A-C)

Invoked by `audit-orchestrator` first, using the shared `SiteInventory`. Answers the first
three questions from the discoverability pipeline:
1. Is the crawler let in? (robots.txt for AI-specific user agents using longest-match precedence)
2. Can it read what's on the page? (raw non-JS HTML; structured data; JSON-LD schema)
3. Can it pick out the specific fact? (facts locked inside images/canvas vs. plain text)

## Inputs
- `inventory`: a loaded `SiteInventory` object or `site_url`.

## Procedure
1. **Crawlability Check:**
   Run `python3 skills/crawl-render-audit/scripts/crawlability_check.py <inventory_json_or_url> --findings-only`.
   - Evaluates AI crawler blocks (GPTBot, ClaudeBot, PerplexityBot, etc.) per path.
   - Checks sitemap.xml and special discovery files (llms.txt, ai.txt).
2. **Render & Data Scan:**
   Run `python3 skills/crawl-render-audit/scripts/render_and_data_scan.py <inventory_json_or_url> --findings-only`.
   - Checks Organization, Product, Offer, Article, FAQPage schema fields.
   - Evaluates the raw, non-JS-executed HTML -- what a non-rendering retrieval bot sees. JS usage alone is never a defect; only an empty raw shell is.
   - Detects facts locked inside canvas or images without alt text.
3. **Extract Ground Truth:**
   Pulls brand name, category, Organization metadata, and core factual claims (founding year, contact) from root schema and text into `inventory.ground_truth`.

## Output
JSON array of structured `CandidateFinding` objects:
```json
{
  "title": "AI crawlers explicitly blocked from root pages (GPTBot, ClaudeBot)",
  "category": "crawlability",
  "severity": "critical",
  "status": "confirmed",
  "confidence": "high",
  "impact": "critical",
  "evidence": "Observed at https://example.com/robots.txt via robots_txt_parser_longest_match [2026-08-29T17:45:00Z]: robots.txt disallows root '/' specifically for: GPTBot, ClaudeBot. (Confidence: high)",
  "source_skill": "crawl-render-audit",
  "fingerprint": "robots:ai-agents-blocked-root",
  "suggested_action": {
    "summary": "Allow AI search and retrieval crawlers to access public brand content.",
    "priority": "critical",
    "how_to_fix": "In robots.txt, remove explicit Disallow rules for retrieval agents or replace them with granular directory restrictions."
  }
}
```
Return candidate findings as a JSON array to the orchestrator.
