"""
site_inventory.py -- Single-pass website crawler and shared inventory cache.
Crawls a website once and caches rich page snapshots for all 6 audit skills.
"""
import sys
import os
import re
import json
import time
from urllib.parse import urlparse, urljoin
from typing import Dict, List, Any, Optional, Set

# Support imports when running as standalone script or module
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from audit_common import (
    AI_USER_AGENTS, DEFAULT_TIMEOUT, USER_AGENT,
    normalize_url, canonicalize, parse_robots, robot_decision,
    visible_text, safe_fetch, classify_access,
    ACCESS_READABLE, ACCESS_ROBOTS_DISALLOWED, ACCESS_AUTH_REQUIRED
)

# Only explicit founding verbs count as an entity founding claim. A bare "since <year>"
# appears constantly in ordinary prose ("supported since 2019", "deprecated since 2017")
# and previously produced high-severity "contradictory founding year" false positives.
FOUNDING_RE = re.compile(r"\b(?:founded|established|incorporated)(?:\s+in)?\s+((?:19|20)\d{2})\b", re.I)
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
# Captures the whole year expression so ranges survive: "(c) 2005-2026" must be read as
# current, not as a stale 2005 notice. Callers take the newest year in the span.
COPYRIGHT_RE = re.compile(
    r"(?:\xa9|&copy;|\(c\)|copyright)\s*((?:19|20)\d{2}(?:\s*(?:[-–—]|to|&ndash;)\s*(?:19|20)\d{2})?)",
    re.I
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
DATED_CLAIM_RE = re.compile(r"\b(?:price|pricing|from|available|availability|in stock|currently|now serving|current(?:ly)?|as of|event|webinar|conference|discount|sale|promo|roadmap)\b[^.!?]{0,100}?\b((?:19|20)\d{2})\b", re.I)
CURRENT_YEAR = time.gmtime().tm_year


def extract_jsonld_blocks(html: str) -> List[str]:
    """Extract raw JSON-LD script blocks from HTML."""
    return re.findall(r'(?is)<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html)


def flatten_jsonld(obj: Any, out: List[Dict[str, Any]]):
    """Recursively flatten JSON-LD nodes including @graph."""
    if isinstance(obj, list):
        for item in obj:
            flatten_jsonld(item, out)
    elif isinstance(obj, dict):
        if "@graph" in obj and isinstance(obj["@graph"], list):
            flatten_jsonld(obj["@graph"], out)
        else:
            out.append(obj)


def parse_jsonld(html: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse JSON-LD scripts, returning (parsed_entities, errors)."""
    blocks = extract_jsonld_blocks(html)
    parsed = []
    errors = []
    for i, b in enumerate(blocks, start=1):
        clean_b = b.strip()
        if not clean_b:
            continue
        try:
            data = json.loads(clean_b)
            flatten_jsonld(data, parsed)
        except Exception as e:
            errors.append({"block_index": i, "error": str(e), "snippet": clean_b[:120]})
    return parsed, errors


COMMERCIAL_TOKENS = {
    "buy", "checkout", "cart", "store", "shop", "product", "products", "solutions",
    "subscribe", "order", "platform", "service", "services"
}
PRICING_TOKENS = {"pricing", "price", "prices", "plans", "plan", "cost", "billing", "subscription"}
EDITORIAL_TOKENS = {
    "docs", "doc", "documentation", "guide", "guides", "faq", "faqs", "help",
    "article", "articles", "blog", "weblog", "news", "learn", "tutorial",
    "tutorials", "whitepaper", "changelog", "release", "releases", "post", "posts"
}
SUPPORT_TOKENS = {
    "contact", "support", "about", "team", "company", "privacy", "terms", "legal", "careers"
}
DATE_SEGMENT_RE = re.compile(r"/(?:19|20)\d{2}(?:/\d{1,2})?(?:/|$)")
RESOURCE_EXTENSIONS = {
    ".svg": "svg",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".avif": "image",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".pdf": "pdf",
    ".woff": "font",
    ".woff2": "font",
    ".ttf": "font",
    ".otf": "font",
    ".eot": "font",
}
CONTENT_TYPES = {
    "image/svg+xml": "svg",
    "text/css": "css",
    "application/javascript": "javascript",
    "text/javascript": "javascript",
    "application/pdf": "pdf",
    "font/woff": "font",
    "font/woff2": "font",
    "application/font-woff": "font",
    "application/vnd.ms-fontobject": "font",
    "font/ttf": "font",
    "font/otf": "font",
}


def tokenize(text: str) -> set:
    """Split text into lowercase word tokens for whole-word keyword matching."""
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t}


def classify_resource_type(url: str, content_type: str = "", body: str = "") -> str:
    """Classify a response before applying document-only audit checks."""
    path = urlparse(url).path.lower()
    for extension, resource_type in RESOURCE_EXTENSIONS.items():
        if path.endswith(extension):
            return resource_type

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        path_tokens = set(part for part in path.split("/") if part)
        if path_tokens.intersection({"fragment", "fragments", "partial", "partials", "component", "components"}):
            return "html_fragment"
        return "html_document"
    if media_type in CONTENT_TYPES:
        return CONTENT_TYPES[media_type]
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("font/"):
        return "font"
    if media_type.startswith("text/") and re.search(r"(?is)<!doctype\s+html|<html\b|<head\b|<body\b", body[:4000]):
        return "html_document"
    if re.search(r"(?is)^\s*(?:<!doctype\s+html|<html\b)", body[:4000]):
        return "html_document"
    return "unknown"


def classify_page_purpose(url: str, title: str, h1_text: str, body_text: str) -> str:
    """
    Classify the primary purpose of a page for context-aware auditing.

    Matches whole tokens, never substrings: '/restore' is not a store, '/workshop' is not a
    shop, and '/buyers-guide' is not a checkout. Editorial routes are resolved before
    commercial ones so a blog post at '/weblog/2025/apr/new-features-.../' is not treated
    as a money page and charged a high-severity 'missing Product/Offer schema' finding.
    """
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")

    path_parts = [part for part in path.split("/") if part]
    if (
        not path
        or path in ("", "/", "/home", "/index.html", "/index.php")
        or (len(path_parts) == 1 and re.fullmatch(r"[a-z]{2}", path_parts[0]))
    ):
        return "homepage"

    path_tokens = tokenize(path)
    combined_tokens = path_tokens | tokenize(title) | tokenize(h1_text)

    if path_tokens.intersection({"fragment", "fragments", "partial", "partials", "component", "components"}):
        return "html_fragment"

    # Editorial first: dated permalinks and doc/blog routes are never money pages.
    if DATE_SEGMENT_RE.search(parsed.path) or (path_tokens & EDITORIAL_TOKENS):
        return "article_docs"
    path_pricing = bool(path_tokens & PRICING_TOKENS)
    heading_pricing = bool((tokenize(title) | tokenize(h1_text)) & PRICING_TOKENS)
    body_pricing = bool(tokenize(body_text) & PRICING_TOKENS)
    price_evidence = bool(re.search(
        r"(?:[$€£₹]\s*\d|\d[\d,.]*\s*(?:USD|EUR|GBP|INR)|\b(?:per month|per year|monthly|annually)\b)",
        body_text or "",
        re.I,
    ))
    pricing_signals = sum((path_pricing, heading_pricing, body_pricing or price_evidence))
    if pricing_signals >= 2 or path_pricing and (heading_pricing or body_pricing or price_evidence):
        return "product_pricing"
    if combined_tokens & COMMERCIAL_TOKENS:
        return "product_landing"
    if combined_tokens & EDITORIAL_TOKENS:
        return "article_docs"
    if combined_tokens & SUPPORT_TOKENS:
        return "contact_support"
    return "general"


def analyze_page_html(
    url: str,
    html: str,
    final_url: str,
    status_code: int,
    load_time: float,
    access_status: Optional[str] = None,
    content_type: str = "",
    resource_type: str = "html_document",
) -> Dict[str, Any]:
    """
    Extract structured analysis from a fetched page's HTML.

    A page we could not actually read is marked `inconclusive` and yields an empty snapshot,
    so no skill can mistake "we failed to decode this" for "this tag is missing". Every
    evaluator checks `inconclusive` before emitting a finding.
    """
    if resource_type != "html_document":
        return {
            "is_page": False,
            "resource_type": resource_type,
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "load_time_seconds": round(load_time, 2) if load_time else None,
            "access_status": classify_access(status_code, html),
            "observation": "Non-HTML response excluded from normal webpage audit checks.",
        }

    access_status = access_status or classify_access(status_code, html)
    if access_status != ACCESS_READABLE:
        if access_status == ACCESS_ROBOTS_DISALLOWED:
            reason = "fetch skipped because robots.txt disallowed this path"
        elif status_code is None:
            reason = f"network access failed: {html or 'unknown network error'}"
        elif access_status == "empty-response":
            reason = "empty response body"
        elif access_status == "undecodable":
            reason = "response body could not be decoded to readable text"
        elif access_status == "anti-bot-challenge":
            reason = f"HTTP {status_code} or response body indicates an anti-bot challenge"
        elif access_status == ACCESS_AUTH_REQUIRED:
            reason = "response is an authentication form; protected content was not assessed"
        elif status_code != 200:
            reason = f"HTTP {status_code}"
        else:
            reason = "page access was inconclusive"
        return {
            "is_page": True,
            "resource_type": "html_document",
            "inconclusive": True,
            "inconclusive_reason": reason,
            "access_status": access_status,
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "load_time_seconds": round(load_time, 2) if load_time else None,
            "raw_html": html or "",
            "visible_text": "",
            "word_count": 0,
            "title": "",
            "meta_description": "",
            "viewport_meta_present": False,
            "canonical_url": None,
            "headings": [],
            "jsonld_blocks": [],
            "jsonld_parsed": [],
            "jsonld_errors": [],
            "internal_links": [],
            "external_links": [],
            "interactive_elements": {"buttons": [], "forms": [], "cta_links": []},
            "media_elements": {"images": [], "canvas_count": 0, "svg_count": 0},
            "dates_and_claims": {},
            "page_purpose": "unknown",
            "is_deep_page": False
        }

    raw_text = visible_text(html)
    words = raw_text.split()

    # Meta tags
    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    title = visible_text(title_m.group(1)) if title_m else ""

    desc_m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html)
    meta_description = desc_m.group(1).strip() if desc_m else ""

    viewport_m = re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I)
    viewport_present = bool(viewport_m)

    site_name_m = re.search(
        r'(?is)<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', html
    )
    og_site_name = site_name_m.group(1).strip() if site_name_m else ""

    canon_m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', html, re.I)
    canonical = canonicalize(final_url, canon_m.group(1).strip()) if canon_m else None

    # Headings
    headings = []
    for h_match in re.finditer(r"(?is)<h([1-3])[^>]*>(.*?)</h\1>", html):
        headings.append({
            "level": int(h_match.group(1)),
            "text": visible_text(h_match.group(2))
        })
    h1_texts = [h["text"] for h in headings if h["level"] == 1]
    primary_h1 = h1_texts[0] if h1_texts else ""

    # JSON-LD
    jsonld_blocks = extract_jsonld_blocks(html)
    jsonld_parsed, jsonld_errors = parse_jsonld(html)

    # Links
    origin = urlparse(final_url).netloc
    internal_links = []
    external_links = []
    seen_hrefs = set()

    for a_match in re.finditer(r'(?is)<a\b([^>]*)>(.*?)</a>', html):
        attrs = a_match.group(1)
        inner_html = a_match.group(2)
        href_m = re.search(r'href=["\'](.*?)["\']', attrs, re.I)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full_url = canonicalize(final_url, href)
        if full_url in seen_hrefs:
            continue
        seen_hrefs.add(full_url)
        link_text = visible_text(inner_html)
        rel_m = re.search(r'rel=["\'](.*?)["\']', attrs, re.I)
        rel = rel_m.group(1).strip() if rel_m else ""

        link_info = {"href": full_url, "text": link_text, "rel": rel}
        if urlparse(full_url).netloc == origin:
            internal_links.append(link_info)
        else:
            external_links.append(link_info)

    # Interactive elements: buttons, forms, CTAs
    buttons = []
    for b_match in re.finditer(r'(?is)<button\b([^>]*)>(.*?)</button>', html):
        b_text = visible_text(b_match.group(2))
        b_type_m = re.search(r'type=["\'](.*?)["\']', b_match.group(1), re.I)
        b_type = b_type_m.group(1) if b_type_m else "button"
        buttons.append({"text": b_text, "type": b_type, "tag": "button"})

    for inp_match in re.finditer(r'(?is)<input\b([^>]*)>', html):
        attrs = inp_match.group(1)
        type_m = re.search(r'type=["\'](submit|button|reset)["\']', attrs, re.I)
        if type_m:
            val_m = re.search(r'value=["\'](.*?)["\']', attrs, re.I)
            val = val_m.group(1) if val_m else type_m.group(1)
            buttons.append({"text": val, "type": type_m.group(1), "tag": "input"})

    for role_b in re.finditer(r'(?is)<(?:div|span|a)\b[^>]*role=["\']button["\'][^>]*>(.*?)</(?:div|span|a)>', html):
        rb_text = visible_text(role_b.group(1))
        if rb_text:
            buttons.append({"text": rb_text, "type": "role_button", "tag": "role_button"})

    forms = []
    for f_match in re.finditer(r'(?is)<form\b([^>]*)>(.*?)</form>', html):
        f_attrs = f_match.group(1)
        f_action_m = re.search(r'action=["\'](.*?)["\']', f_attrs, re.I)
        f_action = f_action_m.group(1) if f_action_m else ""
        f_method_m = re.search(r'method=["\'](.*?)["\']', f_attrs, re.I)
        f_method = f_method_m.group(1) if f_method_m else "GET"
        forms.append({"action": f_action, "method": f_method})

    cta_regex = re.compile(
        r"\b(get started|sign up|sign in|log in|register|try free|start free|buy now|shop now|"
        r"request demo|book demo|contact us|contact sales|subscribe|download|join now|schedule a call|"
        r"view pricing|explore plans|get a quote|add to cart|checkout|talk to sales)\b",
        re.I
    )
    cta_links = []
    for link in internal_links:
        if cta_regex.search(link["text"]):
            cta_links.append(link)

    # Media & Visual Elements
    images = []
    for img_m in re.finditer(r'(?is)<img\b([^>]*)>', html):
        img_attrs = img_m.group(1)
        src_m = re.search(r'src=["\'](.*?)["\']', img_attrs, re.I)
        alt_m = re.search(r'alt=["\'](.*?)["\']', img_attrs, re.I)
        src = canonicalize(final_url, src_m.group(1)) if src_m else ""
        alt = alt_m.group(1).strip() if alt_m else ""
        # alt="" is the CORRECT way to mark a decorative image; a missing alt attribute is the
        # actual defect. Conflating the two would flag every correctly-marked spacer icon.
        images.append({
            "src": src,
            "alt": alt,
            "has_alt": bool(alt),
            "alt_attr_present": alt_m is not None,
            "decorative": alt_m is not None and not alt,
        })

    canvas_count = len(re.findall(r'(?is)<canvas\b', html))
    svg_count = len(re.findall(r'(?is)<svg\b', html))

    # Dates, claims, consistency data.
    # Copyright spans may be ranges ("(c) 2005-2026"); the newest year in the span is the
    # freshness signal. Reading only the first year flagged every ranged footer as stale.
    copyright_matches = []
    for span in COPYRIGHT_RE.findall(raw_text):
        copyright_matches.extend(int(y) for y in YEAR_RE.findall(span))
    newest_copyright = max(copyright_matches) if copyright_matches else None
    founding_matches = sorted(set(FOUNDING_RE.findall(raw_text)))
    phone_matches = sorted(set(PHONE_RE.findall(raw_text)))
    email_matches = sorted(set(EMAIL_RE.findall(raw_text)))

    dated_claims = []
    for dc_m in DATED_CLAIM_RE.finditer(raw_text):
        claim_year = int(dc_m.group(1))
        dated_claims.append({
            "context": dc_m.group(0)[:140],
            "year": claim_year,
            "age_years": CURRENT_YEAR - claim_year
        })

    modified_meta = re.search(r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    last_updated_m = re.search(r"last\s+updated\s*[:\-]?\s*([A-Za-z0-9 ,/\-]{4,25})", raw_text, re.I)

    jsonld_dates = {}
    for node in jsonld_parsed:
        if isinstance(node, dict):
            for k in ("dateModified", "datePublished"):
                if k in node:
                    jsonld_dates[k] = node[k]

    path_parts = [p for p in urlparse(final_url).path.strip("/").split("/") if p]
    is_deep = len(path_parts) >= 2

    # Static shell signals are intentionally conservative. JavaScript usage by itself is not a
    # defect; this only reports a likely gap when the initial response contains a mount marker,
    # very little meaningful text, or a markup-to-text imbalance.
    script_count = len(re.findall(r"(?is)<script\b", html))
    mount_markers = []
    for marker in (r'id=["\'](?:root|app|__next)["\']', r'data-reactroot\b', r'ng-app\b', r'v-app\b'):
        if re.search(marker, html, re.I):
            mount_markers.append(marker)
    shell_signals = []
    if mount_markers:
        shell_signals.append("client-mount-marker")
    if script_count >= 8:
        shell_signals.append("many-inline-or-external-scripts")
    if len(words) < 12:
        shell_signals.append("very-low-readable-text")
    if len(html) > 1500 and len(words) < 30:
        shell_signals.append("markup-to-text-imbalance")
    render_gap = (
        len(words) < 12 and bool(mount_markers)
    ) or (
        len(words) < 30 and not h1_texts and bool(mount_markers or script_count >= 8)
    ) or (
        len(words) < 8 and len(html) > 5000 and script_count >= 3
    )

    purpose = classify_page_purpose(final_url, title, primary_h1, raw_text)

    return {
        "is_page": True,
        "resource_type": "html_document",
        "inconclusive": False,
        "access_status": ACCESS_READABLE,
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "load_time_seconds": round(load_time, 2) if load_time else None,
        "raw_html": html,
        "visible_text": raw_text,
        "word_count": len(words),
        "title": title,
        "meta_description": meta_description,
        "og_site_name": og_site_name,
        "viewport_meta_present": viewport_present,
        "canonical_url": canonical,
        "headings": headings,
        "h1_texts": h1_texts,
        "jsonld_blocks": jsonld_blocks,
        "jsonld_parsed": jsonld_parsed,
        "jsonld_errors": jsonld_errors,
        "internal_links": internal_links,
        "external_links": external_links,
        "interactive_elements": {
            "buttons": buttons,
            "forms": forms,
            "cta_links": cta_links
        },
        "media_elements": {
            "images": images[:25],
            "canvas_count": canvas_count,
            "svg_count": svg_count
        },
        "dates_and_claims": {
            "copyright_years": copyright_matches,
            "newest_copyright_year": newest_copyright,
            "founding_years": [m[0] if isinstance(m, tuple) else m for m in founding_matches],
            "phones": phone_matches,
            "emails": email_matches,
            "dated_claims": dated_claims,
            "stale_dated_claims": [c for c in dated_claims if c["age_years"] >= 2],
            "meta_modified_time": modified_meta.group(1) if modified_meta else None,
            "visible_last_updated": last_updated_m.group(1).strip() if last_updated_m else None,
            "jsonld_dates": jsonld_dates
        },
        "page_purpose": purpose,
        "is_deep_page": is_deep,
        "render_gap": render_gap,
        "render_diff": {
            "available": False,
            "note": "Static inspection performed; no browser rendering was used.",
            "signals": shell_signals,
            "script_count": script_count,
            "mount_markers": mount_markers,
        }
    }


class SiteInventory:
    """Holds shared crawl state, page snapshots, and ground truth for all skills."""

    def __init__(self, site_url: str):
        self.seed_url = normalize_url(site_url)
        p = urlparse(self.seed_url)
        self.origin = f"{p.scheme}://{p.netloc}"
        self.robots_txt = {}
        self.sitemaps = []
        self.special_files = {}
        # Parsed robots groups used to gate our OWN fetches, plus an audit trail of
        # anything we declined to fetch. Populated in crawl_site().
        self._robots_groups = []
        self.skipped_by_robots = []
        # requested_url -> final_url, for URLs that redirected. Snapshots are stored ONCE under
        # their final URL; without this the same page was stored under both keys, so a 5-page
        # crawl reported 6 pages and every "across N crawled pages" evidence string was wrong.
        self.url_aliases: Dict[str, str] = {}
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.ground_truth: Dict[str, Any] = {
            "brand_name": p.netloc.replace("www.", "").split(".")[0].capitalize(),
            "category": "",
            "location": "",
            "key_facts": {}
        }
        self.crawl_budget = {
            "max_pages": 5,
            "http_timeout_seconds": DEFAULT_TIMEOUT,
            "pages_crawled": 0,
            "total_crawl_time_seconds": 0.0,
            "page_selection": []
        }

    def store_page(self, requested_url: str, snap: Dict[str, Any]):
        """Store a snapshot once, keyed by its final URL, recording any redirect alias."""
        final = snap.get("final_url") or requested_url
        self.pages[final] = snap
        if final != requested_url:
            self.url_aliases[requested_url] = final

    def store_resource(self, requested_url: str, resource: Dict[str, Any]):
        """Record a non-page response without exposing it to page-level auditors."""
        final = resource.get("final_url") or requested_url
        self.resources[final] = resource
        if final != requested_url:
            self.url_aliases[requested_url] = final

    def note_resource_candidate(self, url: str, source: str):
        resource_type = classify_resource_type(url)
        self.resources.setdefault(url, {
            "is_page": False,
            "resource_type": resource_type,
            "url": url,
            "final_url": url,
            "status_code": None,
            "content_type": "",
            "access_status": "not-fetched",
            "observation": f"Discovered as a non-HTML {resource_type} resource via {source}; excluded from page checks.",
        })

    def knows_url(self, url: str) -> bool:
        """Have we already fetched this URL, either directly or via a redirect alias?"""
        return url in self.pages or url in self.resources or url in self.url_aliases

    @staticmethod
    def _site_key(netloc: str) -> str:
        """Normalize a host for same-site comparison. apex and www are the same site."""
        netloc = (netloc or "").lower()
        return netloc[4:] if netloc.startswith("www.") else netloc

    def same_site(self, url: str) -> bool:
        """Is this URL on the site being audited, treating apex and www as one?"""
        p = urlparse(url)
        return bool(p.netloc) and self._site_key(p.netloc) == self._site_key(urlparse(self.origin).netloc)

    def may_fetch(self, url: str) -> bool:
        """
        Is this auditor allowed to fetch `url` under the site's robots.txt?

        The handout makes respecting robots.txt an explicit guardrail. We are not a named
        agent, so we resolve against the '*' group. Same-origin only; off-origin URLs are
        never crawled. robots.txt itself and the discovery files are always permitted.
        """
        if not url:
            return False
        if not self.same_site(url):
            return False
        path = urlparse(url).path or "/"
        if path in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/llms-full.txt", "/ai.txt"):
            return True
        if not self._robots_groups:
            return True
        decision = robot_decision(self._robots_groups, "brand-ai-readiness-audit", path)
        if not decision["allowed"]:
            self.skipped_by_robots.append({"url": url, "matched_rule": decision["matched_rule"]})
            return False
        return True

    def crawl_site(self, max_pages: int = 5, timeout: int = DEFAULT_TIMEOUT, additional_paths: Optional[List[str]] = None) -> "SiteInventory":
        """Executes a bounded, single-pass crawl of the site."""
        start_time = time.time()
        self.crawl_budget["max_pages"] = max_pages
        self.crawl_budget["http_timeout_seconds"] = timeout

        # 1. Fetch robots.txt
        robots_url = urljoin(self.origin, "/robots.txt")
        r_status, r_body, _, _, _, _ = safe_fetch(robots_url, timeout=timeout)
        test_paths = ["/", "/pricing", "/products", "/about", "/docs", "/contact"]
        if additional_paths:
            test_paths.extend(additional_paths)
        test_paths = list(dict.fromkeys(test_paths))

        if r_status == 200:
            groups = parse_robots(r_body)
            self._robots_groups = groups
            decisions = {a: {p: robot_decision(groups, a, p) for p in test_paths} for a in AI_USER_AGENTS}
            blocked = {a: [p for p, d in ds.items() if not d["allowed"]] for a, ds in decisions.items()}
            blocked = {a: x for a, x in blocked.items() if x}
            sitemaps_decl = [x.split(":", 1)[1].strip() for x in r_body.splitlines() if x.lower().startswith("sitemap:")]
            self.robots_txt = {
                "found": True,
                "url": robots_url,
                "status": 200,
                "raw": r_body,
                "agent_decisions": decisions,
                "partially_blocked_agents": blocked,
                "sitemaps_declared": sitemaps_decl
            }
        else:
            self.robots_txt = {
                "found": False,
                "url": robots_url,
                "status": r_status,
                "raw": "",
                "agent_decisions": {},
                "partially_blocked_agents": {},
                "sitemaps_declared": []
            }

        # 2. Check special AI discovery files (llms.txt, etc.)
        for spec in ("llms.txt", "llms-full.txt", "ai.txt"):
            u = urljoin(self.origin, "/" + spec)
            s, _, _, _, _, _ = safe_fetch(u, timeout=timeout)
            self.special_files[spec.replace(".", "_")] = {"found": s == 200, "status": s, "url": u}

        # 3. Check declared sitemaps or default /sitemap.xml
        sitemap_candidates = self.robots_txt.get("sitemaps_declared") or [urljoin(self.origin, "/sitemap.xml")]
        sitemap_candidates = list(dict.fromkeys(sitemap_candidates))[:3]
        sitemap_urls_discovered = []
        for sm_url in sitemap_candidates:
            sm_status, sm_body, _, _, _, _ = safe_fetch(sm_url, timeout=timeout)
            found_urls = []
            if sm_status == 200 and sm_body:
                loc_matches = re.findall(r"<loc>(.*?)</loc>", sm_body, re.I)
                found_urls = [u.strip() for u in loc_matches if self.same_site(u.strip())]
                sitemap_urls_discovered.extend(found_urls)
            self.sitemaps.append({
                "url": sm_url,
                "found": sm_status == 200,
                "status": sm_status,
                "discovered_url_count": len(found_urls)
            })

        # 4. Fetch seed/homepage first, subject to the same robots gate as every other page.
        if self.may_fetch(self.seed_url):
            seed_status, seed_html, final_seed_url, _, seed_load_time, seed_headers = safe_fetch(
                self.seed_url, timeout=timeout
            )
            seed_resource_type = classify_resource_type(
                final_seed_url, seed_headers.get("Content-Type", ""), seed_html
            )
            seed_snapshot = analyze_page_html(
                self.seed_url,
                seed_html,
                final_seed_url,
                seed_status,
                seed_load_time,
                content_type=seed_headers.get("Content-Type", ""),
                resource_type=seed_resource_type,
            )
        else:
            seed_status, final_seed_url, seed_load_time = 0, self.seed_url, 0.0
            seed_snapshot = analyze_page_html(
                self.seed_url,
                "",
                self.seed_url,
                seed_status,
                seed_load_time,
                access_status=ACCESS_ROBOTS_DISALLOWED,
            )
        if seed_snapshot.get("is_page", True):
            self.store_page(self.seed_url, seed_snapshot)
        else:
            self.store_resource(self.seed_url, seed_snapshot)

        # Adopt the origin the seed actually resolved to. An apex host that redirects to www
        # (very common) previously left origin on the apex while every page and link lived on
        # www, so the same-site gate refused every internal link and the crawl stopped at one page.
        if seed_status == 200 and final_seed_url:
            fp = urlparse(final_seed_url)
            resolved_origin = f"{fp.scheme}://{fp.netloc}"
            if resolved_origin != self.origin:
                self.origin = resolved_origin

        # 5. Discover representative URLs to complete the inventory up to max_pages.
        # Candidate scoring uses the information already available in the homepage navigation
        # and sitemap; it never fetches extra pages just to choose a page.
        candidates: Dict[str, Dict[str, Any]] = {}
        for index, link_obj in enumerate(seed_snapshot.get("internal_links", [])):
            u = link_obj["href"]
            if classify_resource_type(u) != "unknown":
                self.note_resource_candidate(u, "homepage-link")
                continue
            if not self.knows_url(u):
                candidates.setdefault(u, {"source": "homepage-link", "link_text": link_obj.get("text", ""), "index": index})
        for index, sm_u in enumerate(sitemap_urls_discovered):
            if classify_resource_type(sm_u) != "unknown":
                self.note_resource_candidate(sm_u, "sitemap")
                continue
            if not self.knows_url(sm_u):
                candidates.setdefault(sm_u, {"source": "sitemap", "link_text": "", "index": index})

        purpose_tokens = {
            "product_pricing": {"pricing", "price", "prices", "plans", "plan", "cost", "billing", "checkout", "cart"},
            "product_landing": {"product", "products", "features", "solutions", "buy", "shop", "store", "platform", "service", "services"},
            "article_docs": {"docs", "documentation", "faq", "blog", "guide", "article", "help", "learn", "resources", "news", "research", "api"},
            "contact_support": {"about", "contact", "company", "team", "support", "locations", "location", "campus", "admissions"},
            "audience": {"customers", "industries", "solutions", "use", "cases", "students", "faculty", "patients", "developers"},
        }

        scored_candidates = []
        for url, metadata in candidates.items():
            path_tokens = tokenize(url)
            link_tokens = tokenize(metadata.get("link_text", ""))
            tokens = path_tokens | link_tokens
            score = 0
            signals = []
            for purpose, keywords in purpose_tokens.items():
                overlap = tokens & keywords
                if overlap:
                    score += 12 if purpose == "product_pricing" else 10
                    signals.append(f"{purpose}:{','.join(sorted(overlap))}")
            if metadata["source"] == "homepage-link":
                score += 4
                signals.append("linked-from-homepage")
            else:
                score += 2
                signals.append("listed-in-sitemap")
            depth = len([part for part in urlparse(url).path.split("/") if part])
            if depth == 1:
                score += 2
                signals.append("shallow-route")
            if DATE_SEGMENT_RE.search(url):
                score -= 3
                signals.append("dated-editorial-route")
            purpose = classify_page_purpose(url, metadata.get("link_text", ""), "", "")
            scored_candidates.append({
                "url": url,
                "score": score,
                "signals": signals,
                "purpose_hint": purpose,
                "source": metadata["source"],
            })

        scored_candidates.sort(key=lambda item: (-item["score"], item["url"]))
        selected = []
        selected_purposes = set()
        target_pages = max(0, max_pages - 1)
        # Preserve breadth: choose the highest-scoring page for each distinct purpose first.
        for candidate in scored_candidates:
            purpose = candidate["purpose_hint"]
            if len(selected) >= target_pages:
                break
            if purpose != "general" and purpose not in selected_purposes:
                selected.append(candidate)
                selected_purposes.add(purpose)
        for candidate in scored_candidates:
            if len(selected) >= target_pages:
                break
            if candidate["url"] not in {item["url"] for item in selected}:
                selected.append(candidate)

        self.crawl_budget["page_selection"] = selected
        selected_urls = [item["url"] for item in selected]

        # Fetch candidate pages (robots.txt gated)
        for u in selected_urls[:max_pages - 1]:
            if self.knows_url(u):
                continue
            if not self.may_fetch(u):
                continue
            st, html, fin_u, _, lt, headers = safe_fetch(u, timeout=timeout)
            resource_type = classify_resource_type(fin_u, headers.get("Content-Type", ""), html)
            snap = analyze_page_html(
                u,
                html,
                fin_u,
                st,
                lt,
                content_type=headers.get("Content-Type", ""),
                resource_type=resource_type,
            )
            if snap.get("is_page", True):
                self.store_page(u, snap)
            else:
                self.store_resource(u, snap)

        # 6. Extract ground truth from Organization JSON-LD and root page
        self._extract_ground_truth(seed_snapshot)

        self.crawl_budget["pages_crawled"] = len(self.pages)
        self.crawl_budget["resources_observed"] = len(self.resources)
        access_counts: Dict[str, int] = {}
        for snap in self.pages.values():
            status = snap.get("access_status", "unknown")
            access_counts[status] = access_counts.get(status, 0) + 1
        self.crawl_budget["readable_pages"] = access_counts.get(ACCESS_READABLE, 0)
        self.crawl_budget["access_status_counts"] = access_counts
        self.crawl_budget["total_crawl_time_seconds"] = round(time.time() - start_time, 2)
        return self

    def access_summary(self) -> Dict[str, Any]:
        """Return the access facts needed to interpret evidence-dependent findings."""
        counts = dict(self.crawl_budget.get("access_status_counts", {}))
        readable = self.crawl_budget.get("readable_pages")
        if readable is None:
            readable = sum(
                1 for page in self.pages.values()
                if page.get("access_status") == ACCESS_READABLE
                or (not page.get("inconclusive") and page.get("status_code") == 200)
            )
        return {
            "pages_sampled": len(self.pages),
            "resources_observed": len(self.resources),
            "readable_pages": readable,
            "status_counts": counts,
            "limited": readable == 0,
            "page_selection": self.crawl_budget.get("page_selection", []),
        }

    def assessment_summary(self) -> List[Dict[str, Any]]:
        """Describe what was assessed without converting unavailable evidence into defects."""
        access = self.access_summary()
        readable = access["readable_pages"]
        has_robots = bool(self.robots_txt.get("found"))
        access_status = "confirmed" if readable else "inconclusive"
        access_result = "assessed" if readable else "limited"
        reason = (
            f"{readable} of {access['pages_sampled']} sampled page(s) were readable."
            if readable else
            "No sampled page was readable, so content-dependent checks were not assessed."
        )
        return [
            {
                "check": "page_access",
                "status": access_status,
                "result": access_result,
                "reason": reason,
            },
            {
                "check": "robots_enforcement",
                "status": "confirmed" if has_robots else "not-assessed",
                "result": "passed" if has_robots else "not-assessed",
                "reason": (
                    "robots.txt was fetched and its rules were applied to page and link fetches."
                    if has_robots else
                    "robots.txt was unavailable; no robots policy could be evaluated."
                ),
            },
            {
                "check": "static_render_gap",
                "status": "confirmed" if readable else "inconclusive",
                "result": "assessed" if readable else "limited",
                "reason": (
                    "Initial HTML was inspected for shell signals; no browser rendering was used."
                    if readable else
                    "Initial HTML was unavailable, so render-gap evidence could not be assessed."
                ),
            },
            {
                "check": "citation_answerability",
                "status": "confirmed" if readable else "inconclusive",
                "result": "assessed" if readable else "limited",
                "reason": (
                    "Answerability was checked against accessible on-site text and structured data only."
                    if readable else
                    "No accessible page evidence was available for on-site answerability."
                ),
            },
            {
                "check": "trust_corroboration",
                "status": "confirmed" if readable else "inconclusive",
                "result": "assessed" if readable else "limited",
                "reason": (
                    "Only explicitly linked authority domains were inspected; external sources were not fabricated or searched."
                    if readable else
                    "No readable page was available to inspect for explicit authority links."
                ),
            },
        ]

    def _extract_ground_truth(self, seed_snap: Dict[str, Any]):
        """Extract authoritative ground truth facts from root schema and page text."""
        org_name = None
        name_source = "unknown"
        same_as = []
        founding_date = None
        key_facts = {}

        for ent in seed_snap.get("jsonld_parsed", []):
            t = ent.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Organization", "LocalBusiness", "Corporation", "Brand") for x in types):
                if ent.get("name"):
                    org_name = ent["name"]
                    name_source = "organization_schema"
                if ent.get("sameAs"):
                    sa = ent["sameAs"]
                    same_as.extend(sa if isinstance(sa, list) else [sa])
                if ent.get("foundingDate"):
                    founding_date = ent["foundingDate"]
                if ent.get("description"):
                    key_facts["description"] = ent["description"]

        if not org_name:
            # og:site_name is the site's own declaration of its name.
            org_name = (seed_snap.get("og_site_name") or "").strip() or None
            if org_name:
                name_source = "og_site_name"

        if not org_name:
            # Last resort: a short <title>, then the domain label. The full <title> is usually a
            # tagline ("Welcome to Python.org", "Internet for people, not profit") and previously
            # leaked into generated queries and finding titles as if it were the brand name.
            title_text = (seed_snap.get("title") or "").split("|")[0].split("–")[0].strip()
            if title_text and len(title_text.split()) <= 4:
                org_name = title_text
                name_source = "short_title"
            else:
                label = urlparse(self.seed_url).netloc.replace("www.", "").split(".")[0]
                org_name = label.capitalize() if label else "the brand"
                name_source = "domain_label"

        if org_name:
            self.ground_truth["brand_name"] = org_name
        self.ground_truth["brand_name_source"] = name_source
        if same_as:
            self.ground_truth["same_as"] = same_as
        if founding_date:
            key_facts["founding_year"] = str(founding_date)

        # Pull common facts from all crawled pages
        for snap in self.pages.values():
            dates_info = snap.get("dates_and_claims", {})
            if dates_info.get("founding_years") and "founding_year" not in key_facts:
                key_facts["founding_year"] = dates_info["founding_years"][0]
            if dates_info.get("phones") and "phone" not in key_facts:
                key_facts["phone"] = dates_info["phones"][0]
            if dates_info.get("emails") and "email" not in key_facts:
                key_facts["email"] = dates_info["emails"][0]

        self.ground_truth["key_facts"] = key_facts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed_url": self.seed_url,
            "origin": self.origin,
            "robots_txt": self.robots_txt,
            "sitemaps": self.sitemaps,
            "special_files": self.special_files,
            "pages": self.pages,
            "resources": self.resources,
            "ground_truth": self.ground_truth,
            "crawl_budget": self.crawl_budget,
            "skipped_by_robots": self.skipped_by_robots,
            "url_aliases": self.url_aliases
        }

    def save_json(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiteInventory":
        inv = cls(data.get("seed_url", "https://example.com"))
        inv.origin = data.get("origin", "")
        inv.robots_txt = data.get("robots_txt", {})
        inv.sitemaps = data.get("sitemaps", [])
        inv.special_files = data.get("special_files", {})
        inv.pages = data.get("pages", {})
        inv.resources = data.get("resources", {})
        inv.ground_truth = data.get("ground_truth", {})
        inv.crawl_budget = data.get("crawl_budget", {})
        inv.skipped_by_robots = data.get("skipped_by_robots", [])
        inv.url_aliases = data.get("url_aliases", {})
        # Re-parse robots so a rehydrated inventory still gates its own follow-up fetches
        # (e.g. the engagement broken-link sampler running from a saved inventory).
        raw_robots = (data.get("robots_txt") or {}).get("raw", "")
        inv._robots_groups = parse_robots(raw_robots) if raw_robots else []
        return inv

    @classmethod
    def load_json(cls, filepath: str) -> "SiteInventory":
        with open(filepath, encoding="utf-8-sig") as f:
            return cls.from_dict(json.load(f))


def get_or_crawl_inventory(url_or_path: str, max_pages: int = 5) -> SiteInventory:
    """Helper to load inventory from JSON if a file path is passed, or crawl directly."""
    if os.path.exists(url_or_path) and url_or_path.endswith(".json"):
        return SiteInventory.load_json(url_or_path)
    inv = SiteInventory(url_or_path)
    return inv.crawl_site(max_pages=max_pages)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: site_inventory.py <site_url> [--output inventory.json] [--max-pages 5]"})); sys.exit(1)
    
    url = sys.argv[1]
    output_file = None
    max_pages = 5
    
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
        elif arg == "--max-pages" and i + 1 < len(sys.argv):
            max_pages = int(sys.argv[i + 1])

    inv = SiteInventory(url).crawl_site(max_pages=max_pages)
    if output_file:
        inv.save_json(output_file)
        print(json.dumps({"status": "saved", "output": output_file, "pages_crawled": len(inv.pages)}, indent=2))
    else:
        print(json.dumps(inv.to_dict(), indent=2))


if __name__ == "__main__":
    main()
