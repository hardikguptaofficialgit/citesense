#!/usr/bin/env python3
"""freshness_and_consistency_scan.py -- Appendix D temporal half: is this fact stale, and
does the site agree with itself? Internal signals only. Usage: python3 freshness_and_consistency_scan.py <url1> [<url2> ...]"""
import sys, re, json, urllib.request, urllib.error
from datetime import datetime, timezone

TIMEOUT = 10
CURRENT_YEAR = datetime.now(timezone.utc).year
FOUNDING_RE = re.compile(r"\b(?:founded|established|since|est\.?)\s+(?:in\s+)?((19|20)\d{2})\b", re.I)
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
COPYRIGHT_RE = re.compile(r"(?:\xa9|&copy;|\(c\)|copyright)\s*((19|20)\d{2})", re.I)
AWARD_RE = re.compile(r"\b(award|winner|best\s+\w+|#1|top\s+\d)\b[^.]{0,80}?((19|20)\d{2})", re.I)
DATED_CLAIM_RE = re.compile(r"\b(?:price|pricing|from|available|availability|in stock|currently|now serving|current(?:ly)?|as of|award|winner|certified)\b[^.!?]{0,100}?\b((?:19|20)\d{2})\b", re.I)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "brand-ai-readiness-audit/1.0 (+read-only audit)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, str(e)

def strip_tags_get_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()

def extract_jsonld_dates(html):
    blocks = re.findall(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html)
    dates = {}
    for b in blocks:
        try: data = json.loads(b.strip())
        except json.JSONDecodeError: continue
        for n in (data if isinstance(data, list) else [data]):
            if not isinstance(n, dict): continue
            for k in ("dateModified", "datePublished"):
                if k in n: dates[k] = n[k]
    return dates

def scan_page(url):
    status, html = fetch(url)
    if status != 200:
        return {"url": url, "fetch_status": status, "error": "could not fetch"}
    text = strip_tags_get_text(html)
    modified_meta = re.search(r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    last_updated_visible = re.search(r"last\s+updated\s*[:\-]?\s*([A-Za-z0-9 ,/\-]{4,25})", text, re.I)
    jsonld_dates = extract_jsonld_dates(html)
    founding_matches = sorted(set(m.group(1) for m in FOUNDING_RE.finditer(text)))
    phone_matches = sorted(set(m.group(0) for m in PHONE_RE.finditer(text)))
    copyright_matches = sorted(set(m.group(1) for m in COPYRIGHT_RE.finditer(text)))
    award_candidates = [{"context": m.group(0)[:120], "year": m.group(2)} for m in AWARD_RE.finditer(text)]
    dated_claims = [{"context":m.group(0)[:160],"year":int(m.group(1)),"age_years":CURRENT_YEAR-int(m.group(1))} for m in DATED_CLAIM_RE.finditer(text)]
    stale_copyright = None
    if copyright_matches:
        newest = max(int(y) for y in copyright_matches)
        if CURRENT_YEAR - newest >= 2:
            stale_copyright = {"found_year": newest, "current_year": CURRENT_YEAR, "gap_years": CURRENT_YEAR - newest}
    return {"url": url, "fetch_status": status, "jsonld_dates": jsonld_dates,
            "article_modified_time_meta": modified_meta.group(1) if modified_meta else None,
            "visible_last_updated_text": last_updated_visible.group(1).strip() if last_updated_visible else None,
            "founding_year_mentions": founding_matches, "phone_number_mentions": phone_matches,
            "copyright_year_mentions": copyright_matches, "stale_copyright": stale_copyright,
            "award_mention_candidates": award_candidates, "dated_claim_candidates": dated_claims,
            "stale_dated_claim_candidates":[x for x in dated_claims if x["age_years"] >= 2]}

def cross_page_consistency(pages):
    issues = []
    founding_by_page = {p["url"]: set(p.get("founding_year_mentions", [])) for p in pages if "founding_year_mentions" in p}
    all_years = set()
    for years in founding_by_page.values(): all_years |= years
    if len(all_years) > 1:
        issues.append({"type": "founding_year_mismatch", "years_found": sorted(all_years),
                       "by_page": {u: sorted(y) for u, y in founding_by_page.items() if y}})
    def norm(p): return re.sub(r"\D", "", p)
    phone_by_page = {p["url"]: set(p.get("phone_number_mentions", [])) for p in pages if "phone_number_mentions" in p}
    normalized_groups = {}
    for phones in phone_by_page.values():
        for p in phones: normalized_groups.setdefault(norm(p), set()).add(p)
    if len(normalized_groups) > 1:
        issues.append({"type": "phone_number_mismatch",
                       "distinct_numbers_found": {k: sorted(v) for k, v in normalized_groups.items()},
                       "by_page": {u: sorted(p) for u, p in phone_by_page.items() if p}})
    return issues

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: freshness_and_consistency_scan.py <url1> [<url2> ...]"})); sys.exit(1)
    pages = [scan_page(u) for u in sys.argv[1:]]
    print(json.dumps({"current_year_reference": CURRENT_YEAR, "pages": pages,
                       "cross_page_consistency_issues": cross_page_consistency(pages)}, indent=2))

if __name__ == "__main__":
    main()
