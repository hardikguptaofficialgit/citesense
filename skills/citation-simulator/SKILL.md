---
name: citation-simulator
description: Simulates how a real AI assistant would answer common questions about the brand by actually performing the search-fetch-extract loop described in Appendix B, then classifies each result as correctly answered, omitted, misattributed to the wrong entity, stale, or contradicted across sources. Produces direct evidence that a discoverability problem causes a real answer failure, rather than inferring failure from structural signals alone. Use after crawl-render-audit and freshness-corroboration have established ground-truth facts about the brand.
---

# Citation Simulator (proof-of-failure, not just structural inference)

## Why this skill exists
The other discoverability skills infer failure from structural signals (missing schema, a
blocked crawler, JS-gated content). Those inferences are usually right, but they're still
inference. This skill closes the loop: it runs the process Appendix B describes -- search,
fetch a few pages, build an answer from what's found -- for realistic questions about the
brand, and directly observes whether the answer comes out right.

Run **after** `crawl-render-audit` and `freshness-corroboration` have produced ground-truth
extraction (brand name, category, key offerings, pricing, founding facts, policies).

## Inputs
- `ground_truth`: `{"brand_name": "...", "category": "...", "location": "...", "key_facts": {...}}`
- `site_domain`: the brand's own domain, to check whether results actually drew on it.

## Procedure
1. Run `scripts/generate_queries.py '<ground_truth JSON>'` for the base 9 questions across
   identity / offering / transactional / differentiation / credibility.
2. Add 1-2 questions about the single most prominent, specific offering found during the
   crawl -- generic questions alone under-test specificity, where failures concentrate.
3. For **each** query, actually perform the loop a real assistant would:
   a. Search the web for the query with your own search tool -- don't fetch the brand's own
      site directly; part of what's being tested is whether the brand's pages even surface.
   b. Fetch the top 2-3 results.
   c. Compose the answer based only on what those pages say -- don't fill gaps from general
      knowledge or from `ground_truth`. Reproducing the real gaps is the point.
4. Classify against `ground_truth`:
   - **Correct** -- matches ground truth, cites the brand's own domain or an accurate third
     party. No finding.
   - **Omission** -- only if a bounded search returns no attributable answer despite a confirmed,
     indexable on-site fact; record query, result URLs and dates. No result is otherwise inconclusive.
   - **Misattribution** -- answer confuses the brand with a different entity, or attributes
     another company's facts to it. `citation-misattribution`, **critical** if a name collision.
   - **Staleness** -- answer relies on outdated info contradicting a more recent confirmed
     fact. `citation-staleness`.
   - **Contradiction** -- fetched sources materially disagree and nothing on the brand's own
     site resolves it. `citation-contradiction`.
5. Severity: transactional/identity queries failing -> **high**; differentiation/credibility ->
   **medium**; a single isolated offering-query failure -> **low**, escalate to **medium** if
   the pattern repeats across multiple offering queries.
6. Cap at the 9-11 generated queries -- runtime budget is shared across the whole marketplace.

## Output
Each finding must include the actual simulated question and a concise account of what the
simulated search surfaced -- this IS the evidence, don't summarize it away:
```json
{
  "title": "Assistant search for \"How much does Acme Widgets cost?\" surfaces no pricing information",
  "category": "citation-omission",
  "severity": "high",
  "evidence": "Simulated search returned Acme's homepage and a directory listing, neither containing pricing; ground truth confirms pricing exists on https://example.com/pricing but that page did not surface.",
  "source_skill": "citation-simulator",
  "suggested_action": {
    "summary": "Ensure the pricing page is crawlable, linked from the homepage, and marked up with Product/Offer schema so it surfaces for pricing queries.",
    "priority": "high",
    "how_to_fix": "Cross-check crawl-render-audit's findings for this URL -- likely the same structural gap is already flagged there; this finding is the observed downstream consequence."
  }
}
```
When a citation-simulator finding shares a root cause with a structural finding from another
skill, note the connection in `evidence` so the orchestrator can present them together.
