"""Small, dependency-free primitives shared by read-only audit scripts."""
import re
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
USER_AGENT = "brand-ai-readiness-audit/2.0 (+read-only audit; Adobe Hackathon Round 3)"


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


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Custom redirect handler to track redirect chains manually if needed."""
    pass


def safe_fetch(url: str, method: str = "GET", timeout: int = DEFAULT_TIMEOUT, max_redirects: int = 5):
    """
    Safely fetches a URL, following redirects and recording the status chain.
    Returns: (status_code, body, final_url, redirect_chain, elapsed_seconds, headers)
    """
    req_url = normalize_url(url)
    redirect_chain = []
    current_url = req_url
    start_time = time.time()

    for _ in range(max_redirects + 1):
        redirect_chain.append(current_url)
        try:
            req = urllib.request.Request(
                current_url,
                method=method,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            )
            # Create an opener that doesn't automatically follow redirects silently so we know the status
            class RedirectTracker(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None  # Stop automatic redirect, we handle manually

            opener = urllib.request.build_opener(RedirectTracker)
            try:
                with opener.open(req, timeout=timeout) as response:
                    elapsed = time.time() - start_time
                    body = response.read().decode("utf-8", errors="replace") if method == "GET" else ""
                    headers_dict = dict(response.headers.items()) if hasattr(response, "headers") else {}
                    return response.status, body, current_url, redirect_chain, elapsed, headers_dict
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    loc = e.headers.get("Location")
                    if loc:
                        current_url = canonicalize(current_url, loc)
                        continue
                    else:
                        elapsed = time.time() - start_time
                        return e.code, "", current_url, redirect_chain, elapsed, dict(e.headers.items())
                else:
                    elapsed = time.time() - start_time
                    body = e.read().decode("utf-8", errors="replace") if method == "GET" else ""
                    return e.code, body, current_url, redirect_chain, elapsed, dict(e.headers.items())

        except urllib.error.URLError as e:
            elapsed = time.time() - start_time
            return None, str(e.reason), current_url, redirect_chain, elapsed, {}
        except Exception as e:
            elapsed = time.time() - start_time
            return None, str(e), current_url, redirect_chain, elapsed, {}

    elapsed = time.time() - start_time
    return 310, "Too many redirects", current_url, redirect_chain, elapsed, {}
