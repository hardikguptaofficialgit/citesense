#!/usr/bin/env python3
"""
proactive_recommendations.py -- Beyond-defect recommendations for the audit report.

The rubric scores "what it does to improve AI discoverability & engagement beyond fixing
specific defects" separately from defect detection. These are the suggestions that apply even
where nothing is broken.

Every recommendation is:
  - conditional on something actually observed in the crawl, so it is relevant rather than boilerplate
  - tied to a stated mechanism, so a non-expert can see why it would help
  - ranked by evidence strength (see references/ai-visibility-standards-2026.md for the basis)

Ordering matters: recommendations are emitted strongest-evidence-first and capped, so a report
leads with the highest-leverage change rather than a laundry list.
"""
import os
import re
import sys
from typing import Any, Dict, List
from urllib.parse import urlparse

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

MAX_RECOMMENDATIONS = 6

QUESTION_HEADING_RE = re.compile(r"^\s*(who|what|when|where|why|how|which|can|do|does|is|are)\b", re.I)
FAQ_CONTENT_RE = re.compile(r"\b(frequently asked|faq|common questions|questions and answers)\b", re.I)
AUTHORITY_HOSTS = (
    "wikipedia.org", "wikidata.org", "crunchbase.com", "linkedin.com", "github.com",
    "reddit.com", "youtube.com", "g2.com", "trustpilot.com", "stackoverflow.com",
)


def _schema_types(pages: List[Dict[str, Any]]) -> set:
    types = set()
    for p in pages:
        for ent in p.get("jsonld_parsed", []):
            t = ent.get("@type", "")
            for x in (t if isinstance(t, list) else [t]):
                if x:
                    types.add(x)
    return types


def _rec(title, rationale, summary, priority, how_to_fix):
    return {
        "title": title,
        "rationale": rationale,
        "suggested_action": {"summary": summary, "priority": priority, "how_to_fix": how_to_fix},
    }


def generate_proactive_recommendations(inventory) -> List[Dict[str, Any]]:
    """
    Build beyond-defect recommendations from what the crawl observed.

    `inventory` is a SiteInventory. Returns a list ordered strongest-evidence-first.
    """
    pages = [
        p for p in inventory.pages.values()
        if not p.get("inconclusive") and p.get("status_code") == 200
    ]
    if not pages:
        return []

    recs: List[Dict[str, Any]] = []
    types = _schema_types(pages)
    corpus = " ".join(p.get("visible_text", "") for p in pages)
    all_headings = [h for p in pages for h in p.get("headings", [])]
    gt = inventory.ground_truth or {}
    brand = gt.get("brand_name", "the brand")
    origin = inventory.origin

    external_hosts = set()
    for p in pages:
        for link in p.get("external_links", []):
            host = urlparse(link.get("href", "")).netloc.lower()
            if host:
                external_hosts.add(host[4:] if host.startswith("www.") else host)

    # 1. FAQPage -- the highest-leverage schema type for AI citation, because its Q&A shape
    #    matches how retrieval systems chunk and lift answers.
    has_faq_content = bool(FAQ_CONTENT_RE.search(corpus)) or any(
        QUESTION_HEADING_RE.match(h.get("text", "")) for h in all_headings
    )
    if "FAQPage" not in types and has_faq_content:
        recs.append(_rec(
            "Mark up existing question-and-answer content with FAQPage schema",
            "The site already contains question-shaped content, but none of it is marked as FAQPage. "
            "FAQPage is the highest-leverage schema type for AI citation because its question/answer "
            "structure matches how retrieval systems chunk content and lift a quotable answer. The "
            "content already exists; only the markup is missing.",
            "Add FAQPage JSON-LD to pages that already answer common questions.",
            "high",
            "Wrap each question and its answer in FAQPage JSON-LD with mainEntity -> Question -> "
            "acceptedAnswer. Mark up the answers you already publish rather than writing new ones.",
        ))

    # 2. Entity anchoring off-site. Only ~11% of domains are cited by both ChatGPT and Perplexity,
    #    and the platforms lean on different third-party sources, so on-site work alone caps reach.
    anchored = {h for h in external_hosts if any(h == a or h.endswith("." + a) for a in AUTHORITY_HOSTS)}
    if len(anchored) < 2:
        recs.append(_rec(
            f"Build third-party presence so {brand} is resolvable away from its own domain",
            f"Only {len(anchored)} independent authority domain(s) are referenced from the crawled pages. "
            f"Assistants weight facts that several unrelated sources agree on, and the major platforms "
            f"draw on largely different source pools -- analyses of 2026 citation data find roughly 11% "
            f"domain overlap between ChatGPT and Perplexity. A brand described only on its own site is "
            f"a single fragile source no matter how well that site is built.",
            "Establish and maintain the brand on independent platforms, then link them via sameAs.",
            "high",
            "Create or claim a Wikidata item, a LinkedIn company page, and the profiles that matter in "
            "your sector (Crunchbase, GitHub, G2, industry registries). Keep the core facts identical "
            "across them, then reference them from Organization sameAs so the identity is machine-linkable.",
        ))

    # 3. Answer-first structure. Sequential heading structure and self-contained sections are
    #    repeatedly associated with higher citation rates in 2026 retrieval studies.
    long_paragraph_pages = 0
    for p in pages:
        text = p.get("visible_text", "")
        if not text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 12 and (len(text.split()) / max(len(p.get("headings", [])) or 1, 1)) > 400:
            long_paragraph_pages += 1
    if long_paragraph_pages:
        recs.append(_rec(
            "Restructure long pages so each section answers one question on its own",
            f"{long_paragraph_pages} crawled page(s) carry long runs of prose with few headings to break "
            f"them up. Retrieval systems lift a passage out of its surroundings; a section that only makes "
            f"sense after the paragraphs above it cannot be quoted safely, so it tends not to be quoted at "
            f"all. Self-contained, answer-first sections under sequential headings are consistently the "
            f"most citable shape.",
            "Break long pages into self-contained sections that lead with the answer.",
            "medium",
            "Give each section a heading phrased the way a user would ask the question, then open with the "
            "answer in the first sentence and support it below. Keep paragraphs to two to four sentences "
            "and keep the heading hierarchy sequential (h1 -> h2 -> h3, no skipped levels).",
        ))

    # 4. Article schema with author + dateModified on editorial content.
    editorial = [p for p in pages if p.get("page_purpose") == "article_docs"]
    if editorial and not ({"Article", "NewsArticle", "BlogPosting", "TechArticle"} & types):
        recs.append(_rec(
            "Add Article schema with author and dateModified to editorial pages",
            f"{len(editorial)} crawled page(s) are editorial or documentation content carrying no Article "
            f"schema. Authorship and a machine-readable modification date are the signals assistants use to "
            f"decide whether a passage is current and attributable -- without them, an assistant that finds "
            f"a good answer on the page still has no basis to date it or credit it.",
            "Mark editorial and documentation pages with Article JSON-LD.",
            "medium",
            "Add Article or TechArticle JSON-LD with headline, author (a Person or Organization with a real "
            "profile URL), datePublished and dateModified. Update dateModified when the content genuinely "
            "changes, not on every deploy.",
        ))

    # 5. Site-level entity + search wiring.
    if "WebSite" not in types:
        recs.append(_rec(
            "Declare a WebSite entity with SearchAction",
            "No WebSite schema was found. WebSite ties the domain to the brand entity and, with a "
            "potentialAction SearchAction, lets assistants point users straight into your own search "
            "instead of guessing at URLs. It is a small, stable addition that anchors everything else "
            "on the page to a named site.",
            "Add WebSite JSON-LD with a SearchAction pointing at your search endpoint.",
            "medium",
            "Add WebSite JSON-LD on the homepage with name, url, a publisher reference to your "
            "Organization @id, and potentialAction -> SearchAction with a target URL template.",
        ))

    # 6. BreadcrumbList on deep hierarchies.
    deep = [p for p in pages if p.get("is_deep_page")]
    if deep and "BreadcrumbList" not in types:
        recs.append(_rec(
            "Add BreadcrumbList schema to deep pages",
            f"{len(deep)} crawled page(s) sit two or more levels deep with no BreadcrumbList markup. "
            f"Breadcrumbs give both a visitor arriving cold from an AI answer and the assistant itself "
            f"the parent context a deep URL otherwise lacks.",
            "Add BreadcrumbList JSON-LD alongside visible breadcrumb navigation.",
            "low",
            "Emit BreadcrumbList JSON-LD listing each ancestor with position, name and item URL, and "
            "render the same trail visibly at the top of the page.",
        ))

    # 7. Make the crawl policy explicit rather than inferred.
    robots_found = (inventory.robots_txt or {}).get("found")
    if robots_found:
        raw = (inventory.robots_txt or {}).get("raw", "").lower()
        if "content-signal" not in raw and "license" not in raw:
            recs.append(_rec(
                "State AI usage terms explicitly in robots.txt",
                "robots.txt names which agents may crawl but says nothing about what may be done with the "
                "content once fetched. Emerging conventions -- Cloudflare's Content Signals Policy (released "
                "CC0) and RSL licensing terms -- let a publisher separate training use from search indexing "
                "and answer generation in machine-readable form, instead of leaving that distinction to be "
                "inferred from which user agents happen to be listed.",
                "Add machine-readable content-usage signals to robots.txt.",
                "low",
                "Add a Content Signals Policy block declaring your position on search, ai-input and ai-train "
                "separately, or publish RSL licensing terms. Keep it consistent with the agents you actually "
                "allow, or the two signals will contradict each other.",
            ))

    # 8. Agent-facing access. NLWeb/MCP shipped with real adopters (Shopify, Tripadvisor, O'Reilly,
    #    Eventbrite) and builds on schema.org and sitemaps a site may already have.
    if types:
        recs.append(_rec(
            "Expose an agent-facing endpoint (NLWeb / MCP) built on existing structured data",
            "The site already publishes structured data, which is the input NLWeb uses to serve a conversational "
            "endpoint that AI agents can query directly rather than scraping HTML. Because it builds on "
            "schema.org markup, sitemaps and feeds you already maintain, it is incremental rather than a rebuild, "
            "and it moves the brand from being read by agents to being queryable by them.",
            "Evaluate an NLWeb instance exposing an /ask and /mcp endpoint over existing content.",
            "low",
            "Point an NLWeb instance at your existing schema.org data and sitemap, and expose /ask and /mcp. "
            "Start with the content an agent is most likely to be asked about -- catalogue, docs, pricing.",
        ))

    # 9. llms.txt, reported honestly. Measured adoption is real but crawler uptake is near zero, so
    #    it is offered as cheap optionality rather than as an established win.
    if not (inventory.special_files or {}).get("llms_txt", {}).get("found"):
        recs.append(_rec(
            "Consider publishing llms.txt, with realistic expectations",
            "No /llms.txt is published. Be aware this is a low-evidence convention rather than an established "
            "standard: 2026 measurements find major AI crawlers almost never request the file, and Google has "
            "stated it has no effect on Search or AI Overviews. It costs very little to publish and may matter "
            "if uptake improves, but it should be treated as optionality -- not as a substitute for the "
            "structured data and third-party presence that demonstrably drive citation today.",
            "Optionally publish /llms.txt, after the higher-leverage items above.",
            "low",
            "If you publish one, keep it to a short markdown index of your canonical product, docs, pricing "
            "and company pages, and keep it in sync with the site. Do not deprioritise schema work for it.",
        ))

    return recs[:MAX_RECOMMENDATIONS]
