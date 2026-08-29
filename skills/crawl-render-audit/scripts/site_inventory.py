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
    visible_text, safe_fetch
)

FOUNDING_RE = re.compile(r"\b(?:founded|established|since|est\.?)\s+(?:in\s+)?((?:19|20)\d{2})\b", re.I)
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
COPYRIGHT_RE = re.compile(r"(?:\xa9|&copy;|\(c\)|copyright)\s*((?:19|20)\d{2})", re.I)
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


def classify_page_purpose(url: str, title: str, h1_text: str, body_text: str) -> str:
    """Classify the primary purpose of a page for context-aware auditing."""
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")
    combined = f"{path} {title.lower()} {h1_text.lower()}"

    if not path or path in ("", "/", "/home", "/index.html", "/index.php"):
        return "homepage"
    if any(k in combined for k in ("pricing", "plans", "product", "features", "solutions", "tier", "buy", "store", "shop")):
        return "product_pricing"
    if any(k in combined for k in ("docs", "documentation", "guide", "faq", "help", "article", "blog", "learn", "tutorials", "whitepaper")):
        return "article_docs"
    if any(k in combined for k in ("contact", "support", "about", "team", "company", "privacy", "terms")):
        return "contact_support"
    return "general"


def analyze_page_html(url: str, html: str, final_url: str, status_code: int, load_time: float) -> Dict[str, Any]:
    """Extract structured analysis from a fetched page's HTML."""
    if status_code != 200 or not html:
        return {
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
        images.append({"src": src, "alt": alt, "has_alt": bool(alt)})

    canvas_count = len(re.findall(r'(?is)<canvas\b', html))
    svg_count = len(re.findall(r'(?is)<svg\b', html))

    # Dates, claims, consistency data
    copyright_matches = [int(y) for y in COPYRIGHT_RE.findall(raw_text)]
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

    purpose = classify_page_purpose(final_url, title, primary_h1, raw_text)

    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "load_time_seconds": round(load_time, 2) if load_time else None,
        "raw_html": html,
        "visible_text": raw_text,
        "word_count": len(words),
        "title": title,
        "meta_description": meta_description,
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
        "render_diff": {"available": False, "note": "Static inspection performed"}
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
        self.pages: Dict[str, Dict[str, Any]] = {}
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
            "total_crawl_time_seconds": 0.0
        }

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
                found_urls = [u.strip() for u in loc_matches if urlparse(u.strip()).netloc == urlparse(self.origin).netloc]
                sitemap_urls_discovered.extend(found_urls)
            self.sitemaps.append({
                "url": sm_url,
                "found": sm_status == 200,
                "status": sm_status,
                "discovered_url_count": len(found_urls)
            })

        # 4. Fetch seed/homepage first
        seed_status, seed_html, final_seed_url, _, seed_load_time, _ = safe_fetch(self.seed_url, timeout=timeout)
        seed_snapshot = analyze_page_html(self.seed_url, seed_html, final_seed_url, seed_status, seed_load_time)
        self.pages[self.seed_url] = seed_snapshot
        if final_seed_url != self.seed_url:
            self.pages[final_seed_url] = seed_snapshot

        # 5. Discover representative URLs to complete the inventory up to max_pages
        candidate_urls: List[str] = []

        # From homepage links
        internal_links = seed_snapshot.get("internal_links", [])
        for link_obj in internal_links:
            u = link_obj["href"]
            if u not in self.pages:
                candidate_urls.append(u)

        # From sitemap
        for sm_u in sitemap_urls_discovered:
            if sm_u not in self.pages and sm_u not in candidate_urls:
                candidate_urls.append(sm_u)

        # Categorize candidates into money/pricing, docs/content, and contact/about
        selected_urls = []
        money_urls = [u for u in candidate_urls if any(k in u.lower() for k in ("pricing", "plan", "product", "features", "solutions", "buy"))]
        docs_urls = [u for u in candidate_urls if any(k in u.lower() for k in ("docs", "faq", "blog", "guide", "article", "help"))]
        about_urls = [u for u in candidate_urls if any(k in u.lower() for k in ("about", "contact", "company", "team"))]

        if money_urls:
            selected_urls.append(money_urls[0])
        if docs_urls:
            selected_urls.append(docs_urls[0])
        if about_urls:
            selected_urls.append(about_urls[0])

        # Fill remaining budget with other candidate internal links
        for u in candidate_urls:
            if len(self.pages) + len(selected_urls) >= max_pages:
                break
            if u not in selected_urls:
                selected_urls.append(u)

        # Fetch candidate pages
        for u in selected_urls[:max_pages - 1]:
            if u in self.pages:
                continue
            st, html, fin_u, _, lt, _ = safe_fetch(u, timeout=timeout)
            snap = analyze_page_html(u, html, fin_u, st, lt)
            self.pages[u] = snap
            if fin_u != u:
                self.pages[fin_u] = snap

        # 6. Extract ground truth from Organization JSON-LD and root page
        self._extract_ground_truth(seed_snapshot)

        self.crawl_budget["pages_crawled"] = len(self.pages)
        self.crawl_budget["total_crawl_time_seconds"] = round(time.time() - start_time, 2)
        return self

    def _extract_ground_truth(self, seed_snap: Dict[str, Any]):
        """Extract authoritative ground truth facts from root schema and page text."""
        org_name = None
        same_as = []
        founding_date = None
        key_facts = {}

        for ent in seed_snap.get("jsonld_parsed", []):
            t = ent.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Organization", "LocalBusiness", "Corporation", "Brand") for x in types):
                if ent.get("name"):
                    org_name = ent["name"]
                if ent.get("sameAs"):
                    sa = ent["sameAs"]
                    same_as.extend(sa if isinstance(sa, list) else [sa])
                if ent.get("foundingDate"):
                    founding_date = ent["foundingDate"]
                if ent.get("description"):
                    key_facts["description"] = ent["description"]

        if not org_name:
            # Fallback to title
            t = seed_snap.get("title", "")
            if t:
                org_name = t.split("|")[0].split("-")[0].strip()

        if org_name:
            self.ground_truth["brand_name"] = org_name
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
            "ground_truth": self.ground_truth,
            "crawl_budget": self.crawl_budget
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
        inv.ground_truth = data.get("ground_truth", {})
        inv.crawl_budget = data.get("crawl_budget", {})
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
