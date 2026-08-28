# Severity guide -- crawl-render-audit

| Situation | Severity | Why |
|---|---|---|
| AI-assistant user agent explicitly disallowed while `*` is open | critical | Site believes it's discoverable but has silently opted out the bot that matters |
| Entire site disallowed for `*` with no AI-agent exceptions | critical (verify it isn't an intentional staging/private site first) | Nothing on the site is reachable |
| Core page content js_dependency_ratio > 0.35 | high | Content visible to a human is invisible to a non-executing reader |
| No JSON-LD on a money page (product/service/pricing) | high | The most reliable machine-extractable fact source is absent |
| JSON-LD present but missing schema-required fields | medium | Entity partially resolvable but incomplete |
| Missing title or meta description | medium | Common source of the literal text an assistant quotes as a snippet |
| Missing canonical on a site with duplicate/parameterized URLs | medium | Risk of facts being attributed to the wrong URL |
| No sitemap.xml | medium | Raises discovery cost/latency, not a hard block |
| Missing viewport meta tag | low (discoverability) / feed to engagement-audit too | Mobile-render and mobile-bot rendering both affected |
| llms.txt/ai.txt present | not a finding -- note as existing strength | Emerging convention, absence alone isn't a defect |

## Known AI-assistant crawler user agents (verify current list periodically)
GPTBot, ChatGPT-User, OAI-SearchBot (OpenAI); ClaudeBot, anthropic-ai, Claude-Web (Anthropic);
PerplexityBot, Perplexity-User (Perplexity); Google-Extended (Gemini/AI Overviews);
CCBot (Common Crawl); Amazonbot, Bytespider, Applebot-Extended.

## schema.org types most relevant to AI citation, by page purpose
- Homepage/brand identity: `Organization` (name, url, logo, sameAs)
- Product/e-commerce page: `Product` + nested `Offer` (price, availability)
- Local/physical business: `LocalBusiness` (name, address, openingHours)
- Blog/news/article: `Article`/`NewsArticle` (headline, datePublished, author)
- Help/FAQ content: `FAQPage` (mainEntity list of Question/Answer)
- Site navigation trail: `BreadcrumbList`
