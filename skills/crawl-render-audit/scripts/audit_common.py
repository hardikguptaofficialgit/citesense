"""Small, dependency-free primitives shared by read-only audit scripts."""
import re
import gzip
import zlib
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse, urlunparse

AI_USER_AGENTS = (
    "GPTBot", "ChatGPT-User", "OAI-SearchBot",
    "ClaudeBot", "Claude-Web", "anthropic-ai",
    "PerplexityBot", "Perplexity-User",
    "Google-Extended", "CCBot", "Amazonbot",
    "Applebot-Extended", "Bytespider"
)

DEFAULT_TIMEOUT = 8
USER_AGENT = "brand-ai-readiness-audit/2.1 (+read-only audit; Adobe Hackathon Round 3)"

# Encodings we can decompress with the standard library. Brotli ('br') is deliberately
# not advertised in Accept-Encoding because CPython has no stdlib brotli decoder.
SUPPORTED_ENCODINGS = "gzip, deflate"


def normalize_url(url: str) -> str:
    """Normalize URL by stripping fragments and query trailing whitespace."""
    if not url:
        return ""
    p = urlparse(url.strip())
    # Clean fragment
    return urlunparse((p.scheme, p.netloc, p.path or "/", p.params, p.query, ""))


def canonicalize(base: str, href: str) -> str:
    """Join href to base and normalize."""
    return normalize_url(urljoin(base, href))


def header_get(headers, name: str, default=None):
    """Case-insensitive header lookup. Servers vary on capitalization."""
    if not headers:
        return default
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return default


def decompress_body(raw: bytes, content_encoding: str) -> bytes:
    """
    Decompress a response body.

    Content-Encoding is honoured when present, but we also sniff magic bytes: some CDNs
    (python.org's varnish/Fastly layer among them) return gzip-encoded bodies even when the
    request did not advertise gzip support. Without this, the body decodes to replacement
    characters and every text-derived check reports a false negative.
    """
    if not raw:
        return raw

    enc = (content_encoding or "").lower().strip()
    is_gzip_magic = raw[:2] == b"\x1f\x8b"

    try:
        if enc == "gzip" or is_gzip_magic:
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                # Raw deflate stream without a zlib header
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        # Corrupt or mislabelled stream: hand back the original bytes and let the
        # readability gate downstream mark the page inconclusive.
        return raw

    return raw


def decode_body(raw: bytes, content_type: str) -> str:
    """Decode bytes to text using the declared charset, then the HTML meta charset, then UTF-8."""
    if not raw:
        return ""

    charset = None
    if content_type:
        m = re.search(r"charset=([\w\-]+)", content_type, re.I)
        if m:
            charset = m.group(1)

    if not charset:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w\-]+)', raw[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", errors="ignore")

    for candidate in (charset, "utf-8", "latin-1"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


def content_is_unreadable(text: str) -> bool:
    """
    True when a body decoded to mojibake rather than usable markup.

    Guards the whole finding pipeline: a page we could not actually read must produce
    no findings, because "we could not parse it" is not evidence that a tag is missing.
    """
    if not text:
        return False
    sample = text[:4000]
    if not sample:
        return False
    replacement_ratio = sample.count("�") / len(sample)
    if replacement_ratio > 0.05:
        return True
    # Undecodable binary often survives decoding as control characters
    control = sum(1 for c in sample if ord(c) < 9 or (13 < ord(c) < 32))
    return (control / len(sample)) > 0.05


def parse_robots(text: str):
    """Return robots groups preserving standard consecutive User-agent semantics."""
    groups, agents, rules = [], [], []

    def flush():
        if agents:
            groups.append((tuple(a.lower() for a in agents), tuple(rules)))

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:
                flush()
                agents, rules = [], []
            agents.append(value)
        elif key in ("allow", "disallow") and agents:
            rules.append((key, value))
    flush()
    return groups


def robot_decision(groups, agent: str, path: str = "/"):
    """RFC-style longest matching rule; Allow wins equal-length ties. Empty Disallow allows."""
    agent = agent.lower()
    path = path or "/"
    exact = [g for a, g in groups if agent in a]
    applicable = exact or [g for a, g in groups if "*" in a]
    rules = [rule for group in applicable for rule in group]
    matches = [(kind, prefix) for kind, prefix in rules if prefix and path.startswith(prefix)]
    if not matches:
        return {
            "allowed": True,
            "matched_rule": None,
            "scope": "explicit" if exact else "wildcard/default"
        }
    max_len = max(len(prefix) for _, prefix in matches)
    best = [kind for kind, prefix in matches if len(prefix) == max_len]
    allowed = "allow" in best
    matched_prefix = next(prefix for kind, prefix in matches if len(prefix) == max_len and (kind == "allow") == allowed)
    return {
        "allowed": allowed,
        "matched_rule": ("Allow" if allowed else "Disallow") + ": " + matched_prefix,
        "scope": "explicit" if exact else "wildcard"
    }


def visible_text(html: str) -> str:
    """Extract human-visible text from HTML, stripping non-content blocks."""
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|template|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def safe_fetch(url: str, method: str = "GET", timeout: int = DEFAULT_TIMEOUT, max_redirects: int = 5):
    """
    Safely fetches a URL, following redirects and recording the status chain.
    Decompresses gzip/deflate bodies and decodes using the declared charset.
    Returns: (status_code, body, final_url, redirect_chain, elapsed_seconds, headers)
    """
    req_url = normalize_url(url)
    redirect_chain = []
    current_url = req_url
    start_time = time.time()

    def read_payload(resp):
        headers_dict = dict(resp.headers.items()) if hasattr(resp, "headers") else {}
        if method != "GET":
            return "", headers_dict
        raw = resp.read()
        raw = decompress_body(raw, header_get(headers_dict, "Content-Encoding", ""))
        text = decode_body(raw, header_get(headers_dict, "Content-Type", ""))
        return text, headers_dict

    for _ in range(max_redirects + 1):
        redirect_chain.append(current_url)
        try:
            req = urllib.request.Request(
                current_url,
                method=method,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Encoding": SUPPORTED_ENCODINGS,
                }
            )

            # Opener that does not silently follow redirects, so the status stays visible
            class RedirectTracker(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None

            opener = urllib.request.build_opener(RedirectTracker)
            try:
                with opener.open(req, timeout=timeout) as response:
                    body, headers_dict = read_payload(response)
                    elapsed = time.time() - start_time
                    return response.status, body, current_url, redirect_chain, elapsed, headers_dict
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    loc = e.headers.get("Location")
                    if loc:
                        current_url = canonicalize(current_url, loc)
                        continue
                    elapsed = time.time() - start_time
                    return e.code, "", current_url, redirect_chain, elapsed, dict(e.headers.items())
                body, headers_dict = read_payload(e)
                elapsed = time.time() - start_time
                return e.code, body, current_url, redirect_chain, elapsed, headers_dict

        except urllib.error.URLError as e:
            elapsed = time.time() - start_time
            return None, str(e.reason), current_url, redirect_chain, elapsed, {}
        except Exception as e:
            elapsed = time.time() - start_time
            return None, str(e), current_url, redirect_chain, elapsed, {}

    elapsed = time.time() - start_time
    return 310, "Too many redirects", current_url, redirect_chain, elapsed, {}
