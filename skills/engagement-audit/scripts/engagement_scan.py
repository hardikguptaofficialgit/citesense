#!/usr/bin/env python3
"""engagement_scan.py -- on-site engagement half: why don't visitors who arrive stay?
Orientation, navigation, dead-end/CTA signals, broken-link sample, mobile readiness,
personalization-readiness proxy. Usage: python3 engagement_scan.py <url>"""
import sys, re, json, time, urllib.request, urllib.error
from urllib.parse import urljoin, urlparse

TIMEOUT = 8
MAX_LINKS_TO_CHECK = 8

def fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "brand-ai-readiness-audit/1.0 (+read-only audit)"})
    try:
        start = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed = time.time() - start
            body = resp.read().decode("utf-8", errors="replace") if method == "GET" else ""
            return resp.status, body, elapsed
    except urllib.error.HTTPError as e:
        return e.code, "", None
    except Exception:
        return None, "", None

def strip_tags_get_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()

def extract_internal_links(html, base_url):
    origin = urlparse(base_url).netloc
    links = re.findall(r'(?is)<a\b[^>]+href=["\'](.*?)["\']', html)
    internal, seen, out = [], set(), []
    for href in links:
        if href.startswith(("#", "mailto:", "tel:", "javascript:")): continue
        full = urljoin(base_url, href)
        if urlparse(full).netloc == origin:
            internal.append(full)
    for u in internal:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: engagement_scan.py <url>"})); sys.exit(1)
    url = sys.argv[1]
    status, html, load_time = fetch(url)
    out = {"url": url, "fetch_status": status}
    if status != 200:
        out["error"] = "could not fetch page"
        print(json.dumps(out, indent=2)); return

    out["load_time_seconds"] = round(load_time, 2) if load_time else None

    h1_matches = re.findall(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    h1_texts = [strip_tags_get_text(h) for h in h1_matches]
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    title_text = strip_tags_get_text(title_match.group(1)) if title_match else None
    out["orientation"] = {"h1_count": len(h1_texts), "h1_texts": h1_texts[:3], "title": title_text,
                           "issue_no_h1": len(h1_texts) == 0, "issue_multiple_h1": len(h1_texts) > 1}

    has_nav_landmark = bool(re.search(r"(?is)<nav\b", html)) or bool(re.search(r'role=["\']navigation["\']', html, re.I))
    has_breadcrumbs = bool(re.search(r'(?is)breadcrumb', html))
    internal_links = extract_internal_links(html, url)
    out["navigation"] = {"has_nav_landmark": has_nav_landmark, "has_breadcrumb_markup_or_class": has_breadcrumbs,
                          "internal_link_count": len(internal_links), "issue_too_few_links": len(internal_links) < 3}

    has_search = bool(re.search(r'(?is)type=["\']search["\']|role=["\']search["\']', html))
    cta_words = re.findall(r"(?is)<a[^>]*>\s*([^<]{2,40})\s*</a>", html)
    cta_like = [c.strip() for c in cta_words if re.search(r"\b(get started|contact|buy|shop|learn more|sign up|book|request|try|download|subscribe)\b", c, re.I)]
    out["next_step_signals"] = {"has_site_search": has_search, "cta_like_links_found": len(set(cta_like)),
                                 "sample_cta_text": list(dict.fromkeys(cta_like))[:5], "issue_no_clear_cta": len(cta_like) == 0}

    sample = internal_links[:MAX_LINKS_TO_CHECK]
    broken = []
    for link in sample:
        s, _, _ = fetch(link, method="HEAD")
        if s is None or s >= 400:
            s2, _, _ = fetch(link, method="GET")
            if s2 is None or s2 >= 400:
                broken.append({"url": link, "status": s2})
    out["broken_link_sample"] = {"checked": len(sample), "broken": broken}

    viewport = re.search(r'<meta[^>]+name=["\']viewport["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    out["mobile"] = {"viewport_meta_present": bool(viewport)}

    has_login = bool(re.search(r"(?is)\b(log\s?in|sign\s?in|my account|dashboard)\b", html))
    has_prefs_ui = bool(re.search(r"(?is)\b(save(d)? (for later|preferences)|wishlist|favorite|personalize)\b", html))
    out["personalization_readiness"] = {"account_or_login_signal_found": has_login,
                                         "saved_preference_ui_signal_found": has_prefs_ui,
                                         "note": "surface-level proxy only -- does not confirm backend personalization behavior"}

    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
