# Adding a check without creating a false positive

House rules for anyone — teammate or agent — adding detection logic to this marketplace.
They exist because every rule below was learned from a check that shipped and was wrong.

## The one rule

**A finding asserts that we observed something. Never write evidence describing an observation
the code did not make.**

A check that always fires is not a check. The worst bug this repo has had was a finding whose
evidence read *"Searched external sources for claim X; found 0 independent supporting sources"* —
no search was ever performed, and it fired on every site that stated a founding year. A judge who
verifies one evidence string and finds it untrue discounts the entire report.

If a check needs data we cannot obtain in the deterministic pipeline (live web search, a rendered
DOM, an authenticated view), it belongs in a skill's **agent-supplied mode**, exposed through its
standalone CLI — not simulated with invented inputs.

## Before you write the check

1. **Can it be wrong on a healthy site?** Write that case down first, then write the test for it.
   Every check in `tests/test_new_checks.py` is tested in both directions; the silent case is the
   one that matters.
2. **Is absence really a defect?** `alt=""` is the *correct* way to mark a decorative image.
   A missing `dateModified` on a static page is not staleness. `(c) 2005-2026` is not a stale 2005
   notice. JavaScript use is not a render gap — only an empty raw shell is.
3. **Does the page purpose gate it?** Do not ask "how much does this cost" of a docs site or a
   public agency. Do not demand `Product`/`Offer` schema outside a money page. Use
   `page_purpose`, and remember it is derived from whole tokens, never substrings.
4. **Would a competent site owner disagree?** If yes, it is at most `likely-risk`, not `confirmed`.

## Writing it

Use `create_candidate_finding()` from `models.py`. Never hand-build a finding dict.

```python
create_candidate_finding(
    title="...",                 # the defect, not the fix
    category="...",              # must be in VALID_CATEGORIES
    severity="critical|high|medium|low",
    url=...,                     # where it was observed
    observation="...",           # WHAT WAS COUNTED. Numbers, not adjectives.
    method="...",                # the check that produced it, snake_case
    source_skill="...",
    action_summary="...",        # what to change
    action_priority="...",
    action_how_to_fix="...",     # how, specifically enough to act on
    fingerprint="...",           # see below
    status="confirmed|likely-risk|proactive",
    confidence="high|medium|low",
    impact="...",
)
```

**Observation text must contain what was counted.** "0 of 14 outbound link domains point to an
independent authority" is evidence. "Weak external corroboration" is an opinion.

**Status honestly reflects certainty.** `confirmed` = directly observed and not arguable.
`likely-risk` = observed, but sampling or interpretation could make it wrong. `proactive` = no
defect found, this would still help.

## Fingerprints decide deduplication

- **Template-level defect** (footer, header, `<head>`, anything the CMS renders on every page):
  use a **site-wide** fingerprint with no path — `"engagement:missing-h1"`. The orchestrator merges
  them into one finding whose evidence lists every affected URL. Getting this wrong is how
  mozilla.org once shipped five identical stale-copyright findings.
- **Page-specific defect** (this money page lacks Offer schema): include the path —
  `f"schema:product-offer-missing:{urlparse(url).path}"`.
- **Two skills finding the same root cause**: give them the **same** fingerprint deliberately.
  They merge, and `source_skills` then lists both — which reads as corroboration, not duplication.
  See the identity probe in `citation-simulator` sharing `schema:root-organization-missing`.

## Guardrails that are not negotiable

- **Read-only.** Nothing in this marketplace may alter a live site.
- **robots.txt is enforced**, not merely parsed. Any new fetch goes through
  `SiteInventory.may_fetch()`. Do not call `safe_fetch()` on a site URL directly.
- **Check `inconclusive` first.** A page we could not decode must produce no findings —
  "we failed to parse it" is not evidence that a tag is missing.
- **Stay inside the budget.** Bounded crawl, capped link sampling, no unbounded fan-out.

## Before you push

```bash
python -m unittest discover -s tests -v
```

Then run against at least three sites of different shapes (a docs site, a commercial site, a
non-commercial org) and read the findings as a skeptic. Ask of each one: *if this site's owner
read this, could they show me I was wrong?* If yes, tighten the check or lower its status.

Log what you changed in `Progress.md` — root cause, change, and how you verified it.
