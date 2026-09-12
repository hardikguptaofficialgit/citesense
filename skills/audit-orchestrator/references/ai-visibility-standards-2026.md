# What actually drives AI visibility — evidence basis, September 2026

The field research behind this marketplace's checks and recommendations. Recorded so every
severity and priority in the report can be traced to a reason, and so the next person to touch
the detection logic can tell which claims are well-evidenced and which are speculative.

**Re-verify before the next submission.** Several entries below changed materially during 2026.

---

## 1. AI crawlers are three different things, and blocking them has three different consequences

This is the single most important correction we made. Treating every AI user agent alike
produces false positives against publishers who have made a coherent, deliberate choice.

| Class | Agents | Consequence of blocking |
|---|---|---|
| **Training** | GPTBot, ClaudeBot, Google-Extended, CCBot, Applebot-Extended, Meta-ExternalAgent, Bytespider, Amazonbot | **No citation loss.** Content is kept out of future model training. A legitimate licensing stance. |
| **Search index** | OAI-SearchBot, Claude-SearchBot, PerplexityBot | **Removes the brand from AI search results.** These build the retrieval indexes answers are assembled from. |
| **User-triggered** | ChatGPT-User, Claude-User, Perplexity-User | **Breaks live retrieval.** These fetch a page when a user is literally asking about it. |

The decisions are independent: blocking GPTBot while allowing OAI-SearchBot keeps content out of
training while remaining fully citable. `crawlability_check.py` scores by class — critical when a
citation-critical agent is blocked, low and `proactive` when only training crawlers are.

Note `Claude-Web` and `anthropic-ai` are legacy names; `Claude-User` and `Claude-SearchBot` are
the current ones.

## 2. Structured data is the best-evidenced on-site lever

- **FAQPage is the highest-leverage type for AI citation.** Its question/answer shape matches how
  retrieval systems chunk content and lift a quotable answer. This is why our FAQPage
  recommendation is `high` priority and fires only when question-shaped content already exists —
  the content is there, only the markup is missing.
- **Organization is foundational.** It anchors the entity graph; without it, other schema types
  have less to attach to. This is why a missing Organization is a *finding*, not a suggestion.
- A study of 1,000 Google AI Overviews found schema-marked pages cited more often than
  unstructured equivalents **after controlling for domain authority** — i.e. the markup itself
  carries signal, not just the fact that better sites tend to have it.

## 3. Off-site presence caps what on-site work can achieve

- Analyses of 2026 citation data find roughly **11% domain overlap between ChatGPT and
  Perplexity** — the platforms draw on largely different source pools.
- ChatGPT citations lean heavily on Reddit, Wikipedia and news; Reddit was Perplexity's single
  largest source through much of 2025.
- Consequence: a brand described only on its own domain is one fragile source however well that
  domain is built. This is the mechanism behind both the `trust-corroboration-graph` identity-anchor
  finding and the `high`-priority third-party-presence recommendation.

## 4. Content shape decides whether a passage can be lifted

Retrieval lifts a passage out of its surroundings, so a section that only makes sense after the
paragraphs above it cannot be quoted safely.

- Sequential heading structure is associated with materially higher citation odds (~2.8x in
  reported 2026 analyses).
- Each section should cover one concept, lead with the answer, and stand alone.
- Two-to-four-sentence paragraphs reduce ambiguity during extraction.
- Question-led headings mirror the query a user or engine would issue.
- Content that builds to its conclusion tends to fail retrieval — assistants scan for immediate
  relevance rather than reading to the end.
- Inline citations to primary sources score better in RAG retrieval.

## 5. llms.txt: real adoption, near-zero crawler uptake

Treat with care — it is widely recommended and weakly evidenced.

- Adoption is roughly 8–10% of top domains after ~18 months.
- Across a monitored window of 500M+ AI bot visits, only **408** requests targeted `/llms.txt`.
  GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot and Google-Extended overwhelmingly skip it and
  crawl HTML directly.
- **Google stated in June 2026 that llms.txt has no effect** — positive or negative — on Search or
  AI Overviews.
- No major AI provider has publicly committed to reading it in production.

We therefore recommend it at `low` priority with the evidence stated plainly, rather than
presenting it as an established win. Absence of llms.txt is **never** a finding.

## 6. Emerging, worth knowing, not yet load-bearing

- **Cloudflare Content Signals Policy** (released CC0) extends robots.txt to express what may be
  done with content once fetched — separating search, AI input and AI training — rather than
  leaving that inferred from which agents are named.
- **RSL (Really Simple Licensing)**, launched September 2025, adds machine-readable licensing terms
  to robots.txt. Backers include Medium, Akamai, Cloudflare, Yahoo. Legally grounded, adoption-limited.
- **NLWeb** (Microsoft) turns a site into a conversational endpoint agents can query, exposing
  `/ask` and `/mcp`, built on schema.org, RSS and sitemaps a site likely already has. Adopters
  include Shopify, Tripadvisor, O'Reilly, Eventbrite, Hearst.
- **Universal Commerce Protocol (UCP)**, Shopify + Google, launched January 2026 with Etsy, Target,
  Walmart, Wayfair. Relevant to commerce sites specifically.

These drive `low`-priority recommendations: real enough to mention, too early to treat their
absence as a defect.

---

## How this maps to the code

| Evidence | Where it lands |
|---|---|
| Crawler class taxonomy | `audit_common.AI_CRAWLER_CLASSES`, `crawlability_check.py` severity |
| FAQPage leverage | proactive rec 1 (`high`) |
| Organization as anchor | `render_and_data_scan.py` finding; `citation-simulator` identity probe |
| Third-party presence | `corroboration_scorer.evaluate_identity_anchoring`; proactive rec 2 (`high`) |
| Content chunking | proactive rec 3 (`medium`) |
| Article author/dateModified | proactive rec 4 (`medium`) |
| WebSite + SearchAction | proactive rec 5 (`medium`) |
| BreadcrumbList | proactive rec 6 (`low`) |
| Content Signals / RSL | proactive rec 7 (`low`); training-only-blocked finding |
| NLWeb / MCP | proactive rec 8 (`low`) |
| llms.txt reality check | proactive rec 9 (`low`), never a finding |

## Sources

- [llms.txt adoption and crawler uptake, 2026](https://ai.aeo.press/the-state-of-llms-txt-in-2026)
- [llms.txt in practice: adoption data and evidence](https://www.digitalapplied.com/blog/llms-txt-in-practice-adoption-evidence-2026)
- [AI crawler user agents: 2026 reference](https://www.honeyb.ai/blog/ai-crawler-user-agents-reference-2026)
- [Which AI crawlers to allow in robots.txt, 2026](https://www.cite.sh/blog/ai-crawler-guide/)
- [The AI citation economy: 1M+ data points](https://otterly.ai/blog/the-ai-citations-report-2026/)
- [ChatGPT vs Perplexity vs Google AI citation benchmarks](https://www.averi.ai/how-to/chatgpt-vs.-perplexity-vs.-google-ai-mode-the-b2b-saas-citation-benchmarks-report-(2026))
- [Schema markup for Perplexity AI](https://aigrowthagent.co/articles/schema-markup-perplexity-ai/)
- [Content chunking and AI extractability](https://www.lumar.io/blog/best-practice/content-chunking-ai-extractability-geo-aeo-explainer/)
- [AEO content structure best practices](https://www.airops.com/blog/aeo-content-structure)
- [Cloudflare Content Signals Policy](https://www.businesswire.com/news/home/20250924718008/en/Cloudflare-Gives-Creators-New-Tool-to-Control-Use-of-Their-Content)
- [Really Simple Licensing](https://en.wikipedia.org/wiki/Really_Simple_Licensing)
- [MCP, A2A, NLWeb and AGENTS.md: standards powering the agentic web](https://www.searchenginejournal.com/mcp-a2a-nlweb-and-agents-md-the-standards-powering-the-agentic-web/570092/)
- [Optimizing your site for agents with NLWeb and MCP](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/the-future-of-ai-optimize-your-site-for-agents---its-cool-to-be-a-tool/4434189)
