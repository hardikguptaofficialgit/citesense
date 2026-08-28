"""Small, dependency-free primitives shared by read-only audit scripts."""
import re
from urllib.parse import urljoin, urlparse

AI_USER_AGENTS = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web",
                  "PerplexityBot", "Google-Extended", "CCBot", "Amazonbot", "Applebot-Extended")

def normalize_url(url):
    p = urlparse(url)
    return p._replace(fragment="").geturl()

def parse_robots(text):
    """Return robots groups preserving standard consecutive User-agent semantics."""
    groups, agents, rules = [], [], []
    def flush():
        if agents: groups.append((tuple(a.lower() for a in agents), tuple(rules)))
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line: continue
        key, value = (x.strip() for x in line.split(":", 1)); key = key.lower()
        if key == "user-agent":
            if rules: flush(); agents, rules = [], []
            agents.append(value)
        elif key in ("allow", "disallow") and agents:
            rules.append((key, value))
    flush()
    return groups

def robot_decision(groups, agent, path="/"):
    """RFC-style longest matching rule; Allow wins equal-length ties. Empty Disallow allows."""
    agent = agent.lower()
    exact = [g for a, g in groups if agent in a]
    applicable = exact or [g for a, g in groups if "*" in a]
    rules = [rule for group in applicable for rule in group]
    matches = [(kind, prefix) for kind, prefix in rules if prefix and path.startswith(prefix)]
    if not matches: return {"allowed": True, "matched_rule": None, "scope": "explicit" if exact else "wildcard/default"}
    max_len = max(len(prefix) for _, prefix in matches)
    best = [kind for kind, prefix in matches if len(prefix) == max_len]
    allowed = "allow" in best
    return {"allowed": allowed, "matched_rule": ("Allow" if allowed else "Disallow") + ": " + next(prefix for kind,prefix in matches if len(prefix)==max_len and (kind=="allow") == allowed), "scope": "explicit" if exact else "wildcard"}

def visible_text(html):
    html = re.sub(r"(?is)<(script|style|template|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()

def canonicalize(base, href): return normalize_url(urljoin(base, href))
