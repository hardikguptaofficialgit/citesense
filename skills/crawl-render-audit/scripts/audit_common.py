"""Small, dependency-free primitives shared by read-only audit scripts."""
import re
import gzip
import io
import ipaddress
import socket
import zlib
import time
import threading
import urllib.request
import urllib.error
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

# AI crawlers split into three classes that have completely different consequences when blocked.
# Treating them alike is a false positive: a publisher who blocks training crawlers but allows
# search and user-triggered ones has made a deliberate, coherent licensing choice and is still
# fully citable. Only the last two classes decide whether a brand can appear in an answer.
#
#   training       -- harvest content for future model training. Blocking costs no citations.
#   search_index   -- build the retrieval indexes AI answers are assembled from. Blocking these
#                     removes the brand from AI search results.
#   user_triggered -- fetch a page live when a user asks about it. Blocking these breaks the
#                     assistant's ability to read the page the user is literally asking about.
AI_CRAWLER_CLASSES = {
    "training": (
        "GPTBot", "ClaudeBot", "Google-Extended", "CCBot",
        "Applebot-Extended", "Meta-ExternalAgent", "Bytespider", "Amazonbot",
    ),
    "search_index": (
        "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot",
    ),
    "user_triggered": (
        "ChatGPT-User", "Claude-User", "Perplexity-User",
    ),
}

CITATION_CRITICAL_AGENTS = AI_CRAWLER_CLASSES["search_index"] + AI_CRAWLER_CLASSES["user_triggered"]

AI_USER_AGENTS = tuple(a for group in AI_CRAWLER_CLASSES.values() for a in group)


def crawler_class(agent: str) -> str:
    """Which consequence class does this user agent belong to?"""
    for name, agents in AI_CRAWLER_CLASSES.items():
        if agent in agents:
            return name
    return "unknown"

DEFAULT_TIMEOUT = 8
USER_AGENT = "brand-ai-readiness-audit/2.1 (+read-only audit; Adobe Hackathon Round 3)"

# Encodings we can decompress with the standard library. Brotli ('br') is deliberately
# not advertised in Accept-Encoding because CPython has no stdlib brotli decoder.
SUPPORTED_ENCODINGS = "gzip, deflate"

ACCESS_READABLE = "readable"
ACCESS_ROBOTS_DISALLOWED = "robots-disallowed"
ACCESS_ANTI_BOT = "anti-bot-challenge"
ACCESS_HTTP_BLOCKED = "http-blocked"
ACCESS_HTTP_ERROR = "http-error"
ACCESS_NETWORK_ERROR = "network-error"
ACCESS_EMPTY = "empty-response"
ACCESS_UNREADABLE = "undecodable"
ACCESS_AUTH_REQUIRED = "authentication-required"
ACCESS_RESPONSE_TOO_LARGE = "response-too-large"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
SAFE_HTTP_PORTS = {80, 443}
RESPONSE_TOO_LARGE_MARKER = "[citesense:response-too-large]"
READ_TIMEOUT_MARKER = "[citesense:read-timeout]"
FETCH_REJECTED_MARKER = "[citesense:fetch-rejected]"

ANTI_BOT_MARKER_RE = re.compile(
    r"(?is)(?:captcha|recaptcha|verify\s+you(?:r)?self|verify\s+you\s+are\s+human|"
    r"checking\s+your\s+browser|attention\s+required|access\s+denied|bot\s+detection|"
    r"unusual\s+traffic|enable\s+javascript\s+and\s+cookies|ddos\s+protection|"
    r"perimeterx|akamai\s+bot)"
)


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


class _ResponseTooLarge(Exception):
    """Internal signal used to stop reading oversized raw or decompressed bodies."""


class _ResponseTimeout(Exception):
    """Internal signal used to stop a continuously streaming response at the deadline."""


def _decompress_bounded(raw: bytes, content_encoding: str, max_bytes: int) -> bytes:
    """Decompress while bounding expansion, preventing compressed-body bombs."""
    enc = (content_encoding or "").lower().strip()
    is_gzip_magic = raw[:2] == b"\x1f\x8b"
    try:
        if enc == "gzip" or is_gzip_magic:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                output = stream.read(max_bytes + 1)
            if len(output) > max_bytes:
                raise _ResponseTooLarge
            return output
        if enc == "deflate":
            for window_bits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
                try:
                    decoder = zlib.decompressobj(window_bits)
                    output = decoder.decompress(raw, max_bytes + 1)
                    output += decoder.flush(max_bytes + 1 - len(output))
                    if len(output) > max_bytes or decoder.unconsumed_tail:
                        raise _ResponseTooLarge
                    return output
                except zlib.error:
                    continue
    except _ResponseTooLarge:
        raise
    except Exception:
        return raw
    if len(raw) > max_bytes:
        raise _ResponseTooLarge
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


def classify_access(status_code: Optional[int], body: str = "") -> str:
    """Classify whether a response is readable without bypassing access controls."""
    sample = (body or "")[:12000]
    if sample.startswith(RESPONSE_TOO_LARGE_MARKER):
        return ACCESS_RESPONSE_TOO_LARGE
    if status_code is None:
        return ACCESS_NETWORK_ERROR
    if status_code in (401, 403, 429, 503):
        if re.search(
            r"(?is)(?:captcha|recaptcha|verify\s+you(?:r)?self|verify\s+you\s+are\s+human|"
            r"checking\s+your\s+browser|unusual\s+traffic|enable\s+javascript\s+and\s+cookies|"
            r"ddos\s+protection|perimeterx|akamai\s+bot)",
            sample,
        ):
            return ACCESS_ANTI_BOT
        return ACCESS_HTTP_BLOCKED
    if ANTI_BOT_MARKER_RE.search(sample):
        return ACCESS_ANTI_BOT
    if status_code == 200 and re.search(
        r"(?is)<form\b[^>]*>.*?(?:type=[\"']password|name=[\"']password|"
        r"\b(?:sign|log)[\s-]?in\b).*?</form>",
        sample,
    ):
        return ACCESS_AUTH_REQUIRED
    if status_code != 200:
        return ACCESS_HTTP_ERROR
    if not body:
        return ACCESS_EMPTY
    if content_is_unreadable(body):
        return ACCESS_UNREADABLE
    return ACCESS_READABLE


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


def _resolve_public_addresses(hostname: str, port: int, timeout: float):
    """Resolve a host on a daemon thread so a stuck system resolver cannot hang an audit."""
    result = []
    error = []

    def resolve():
        try:
            result.extend(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
        except (OSError, socket.gaierror) as exc:
            error.append(exc)

    worker = threading.Thread(target=resolve, daemon=True)
    worker.start()
    worker.join(max(0.0, timeout))
    if worker.is_alive():
        return None, "hostname resolution timed out"
    if error:
        return None, "hostname could not be resolved"
    return result, None


def _fetch_target_error(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[str]:
    """Reject unsafe network targets before urllib performs a connection."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return "unsupported or malformed URL"
    if parsed.username or parsed.password:
        return "URL credentials are not allowed"
    try:
        port = parsed.port
    except ValueError:
        return "invalid URL port"
    if port is not None and port not in SAFE_HTTP_PORTS:
        return f"unsafe HTTP port: {port}"

    hostname = parsed.hostname.strip().rstrip(".")
    resolved, resolve_error = _resolve_public_addresses(
        hostname,
        port or (443 if parsed.scheme.lower() == "https" else 80),
        timeout,
    )
    if resolve_error:
        return resolve_error
    addresses = {result[4][0] for result in resolved}
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return "resolved address was invalid"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
            or str(ip) == "169.254.169.254"
        ):
            return f"resolved address is not public: {ip}"
    return None


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
        content_length = header_get(headers_dict, "Content-Length")
        try:
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise _ResponseTooLarge
        except ValueError:
            pass
        deadline = time.monotonic() + max(0.001, float(timeout))
        chunks = []
        bytes_read = 0
        while bytes_read <= MAX_RESPONSE_BYTES:
            if time.monotonic() >= deadline:
                raise _ResponseTimeout
            chunk = resp.read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - bytes_read))
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
        if bytes_read > MAX_RESPONSE_BYTES:
            raise _ResponseTooLarge
        raw = b"".join(chunks)
        raw = _decompress_bounded(
            raw,
            header_get(headers_dict, "Content-Encoding", ""),
            MAX_RESPONSE_BYTES,
        )
        text = decode_body(raw, header_get(headers_dict, "Content-Type", ""))
        return text, headers_dict

    for _ in range(max_redirects + 1):
        redirect_chain.append(current_url)
        target_error = _fetch_target_error(current_url, timeout=timeout)
        if target_error:
            elapsed = time.time() - start_time
            return None, f"{FETCH_REJECTED_MARKER} {target_error}", current_url, redirect_chain, elapsed, {}
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

        except _ResponseTooLarge:
            elapsed = time.time() - start_time
            return None, RESPONSE_TOO_LARGE_MARKER, current_url, redirect_chain, elapsed, {}
        except _ResponseTimeout:
            elapsed = time.time() - start_time
            return None, READ_TIMEOUT_MARKER, current_url, redirect_chain, elapsed, {}
        except urllib.error.URLError as e:
            elapsed = time.time() - start_time
            return None, str(e.reason), current_url, redirect_chain, elapsed, {}
        except Exception as e:
            elapsed = time.time() - start_time
            return None, str(e), current_url, redirect_chain, elapsed, {}

    elapsed = time.time() - start_time
    return 310, "Too many redirects", current_url, redirect_chain, elapsed, {}
