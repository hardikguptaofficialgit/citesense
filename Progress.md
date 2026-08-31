# Progress Log — CiteSense

Working log for the Adobe University Hackathon 2026 Round 3 submission.
**Audience: teammates and their AI coding agents.** Read this before touching the repo.

---

## How to use this file

- Every fix gets an entry under **Fixed**, with the root cause, the change, and how it was verified.
- Anything known-broken but not yet fixed lives under **Open**, ranked by impact on the rubric.
- If you fix something, move it from **Open** to **Fixed** and record your verification command.
- Don't claim a fix without a reproduction. Every entry below has one.

## Current status — 2026-08-31

| | |
|---|---|
| Tests | **79 passing**, stdlib only (21 original + 36 regression + 22 new-check) |
| Fixes landed | **F1–F27** across five batches |
| False positives removed | 4 high on python.org, 1 high on react.dev, 1 high on django, 10 duplicate lows |
| Fabricated evidence strings | **0** (swept across all six validation reports) |
| Skills contributing findings | **6 of 6** (was 4 of 6) |
| Discoverability:engagement | ~2:1 (was ~5:1) |
| robots.txt | **enforced**, verified against a local disallow server |
| Schema compliance | all six validation reports validate with real `jsonschema` |
| Slowest audit | 11.9s (stripe.com) against a 5-minute budget |
| Still open | nothing tracked — see Known limitations |

## Quick verification commands

```bash
python -m unittest discover -s tests -v
```

```bash
python skills/audit-orchestrator/scripts/run_audit.py https://www.python.org --output py.json
```

Sweep every validation report for evidence describing an observation we never made — this must
always print `0`:

```bash
python -c "import json,glob;print(sum('Searched external sources' in f['evidence'] for p in glob.glob('validation-runs/*-report.json') for f in json.load(open(p,encoding='utf-8'))['findings']))"
```

---

## Context: why this log exists

An end-to-end review on 2026-08-31 ran the orchestrator live against four real sites
(python.org, react.dev, mozilla.org, djangoproject.com) and found that the marketplace
**structure** is sound but the **detection layer** emitted false positives on the majority
of them. The rubric's heaviest criterion is "correctly identifies the real problems
(evidence-backed) ... with few misses and few false positives", so these are submission-blocking.

Architecture that was reviewed and found good (do not rewrite):
- `marketplace.json` manifest, exactly one entrypoint, 6 agentskills.io-compliant skill folders
- Shared single-pass `SiteInventory` consumed by the specialist skills
- `CandidateFinding` contract + root-cause dedup + schema validation
- robots.txt parser with longest-match precedence (the parser is correct; it just wasn't enforced)
- Zero external dependencies, well under the 5-minute runtime budget

---

## Fixed

### 2026-08-31 — Batch 1: false-positive elimination + robots enforcement

Net effect across the four review sites, before → after:

| Site | Findings before | Findings after | High-severity FPs removed |
|---|---|---|---|
| python.org | 8 (4 high) | 3 | 4 |
| react.dev | 5 (1 high) | 3 | 1 |
| mozilla.org | 11 (1 high) | 4 | 0 (5 duplicate lows removed) |
| djangoproject.com | 11 (1 high) | 3 | 1 |

All 21 unit tests still pass.

---

**F1 — `safe_fetch` now decompresses gzip/deflate and decodes by declared charset.**
`skills/crawl-render-audit/scripts/audit_common.py`

- *Root cause:* the body was read as `response.read().decode("utf-8", errors="replace")` with no
  `Content-Encoding` handling. python.org's varnish/Fastly layer returns gzip even when the request
  does not advertise it, so the auditor parsed binary noise as HTML.
- *Change:* added `decompress_body()` (honours `Content-Encoding`, and sniffs the `\x1f\x8b` gzip
  magic bytes for servers that compress unsolicited), `decode_body()` (Content-Type charset →
  HTML meta charset → UTF-8 → latin-1), and a case-insensitive `header_get()` because servers
  disagree on header capitalization. `Accept-Encoding: gzip, deflate` is now sent. Brotli is
  deliberately *not* advertised — CPython has no stdlib decoder for it.
- *Verified:* python.org went from 11,005 chars of mojibake to 52,902 chars of real HTML with a
  parseable `<title>`. Re-tested against 7 sites; all decode cleanly.
- *Impact:* removed 4 false high-severity findings on python.org alone (missing title, missing h1,
  missing viewport, zero internal links).

**F2 — Unreadable pages are now marked `inconclusive` and emit no findings.**
`site_inventory.py`, `render_and_data_scan.py`, `engagement_scan.py`, `freshness_and_consistency_scan.py`

- *Root cause:* structural depth-charge behind F1 — any page we failed to decode looked to every
  evaluator like a page that was genuinely missing every tag.
- *Change:* added `content_is_unreadable()` (replacement-char and control-char ratio test).
  `analyze_page_html()` returns a snapshot flagged `inconclusive: True` with a reason string;
  all four evaluators check it before emitting anything.
- *Why it matters beyond F1:* "we could not parse it" is not evidence that a tag is missing. This
  makes the guarantee structural rather than relying on the fetch layer always succeeding.

**F3 — Copyright year ranges are read as current.**
`site_inventory.py`, `freshness_and_consistency_scan.py`

- *Root cause:* `COPYRIGHT_RE` captured only the first year of a span, so Mozilla's `©1998–2026`
  and Django's `© 2005-2026` were reported as stale notices from 1998 and 2005.
- *Change:* the regex now captures the whole year expression including the range tail
  (`-`, `–`, `—`, `to`, `&ndash;`), and callers take the newest year in the span.
- *Verified:* both sites stop reporting stale copyright. Removed 10 false findings across the two.

**F4 — `since <year>` in prose no longer counts as a founding claim.**
`site_inventory.py`

- *Root cause:* `FOUNDING_RE` matched bare `since`, which appears constantly in ordinary prose.
  react.dev has "since 2019" on `/blog` and "since 2017" on `/community/team` — neither is a
  founding claim — and this produced a **high** severity "Inconsistent founding year claimed
  across site pages (2017, 2019)".
- *Change:* the pattern now requires an explicit founding verb (`founded` / `established` /
  `incorporated`, optionally followed by `in`). Bare `since` and the noisy `est.` form are gone.
- *Verified:* react.dev's high-severity founding-year finding is gone.

**F5 — Page-purpose classification matches whole tokens, editorial routes resolve first.**
`site_inventory.py`

- *Root cause:* substring matching with no word boundaries. `/restore`→`store`,
  `/workshop`→`shop`, `/buyers-guide`→`buy`, `/frontier-guide`→`tier` all classified as
  `product_pricing`, which then charged them a **high** "Missing Product/Offer structured data on
  commercial page". On djangoproject.com a blog post at
  `/weblog/2025/apr/26/new-features-github-repo-and-project/` matched `features` and became the
  report's only high-severity finding.
- *Change:* added `tokenize()` and three token sets (`COMMERCIAL_TOKENS`, `EDITORIAL_TOKENS`,
  `SUPPORT_TOKENS`). Editorial routes — including dated permalinks matched by `DATE_SEGMENT_RE` —
  are resolved *before* commercial ones, so a blog post is never a money page. Dropped `features`
  and `tier` from the commercial set: both are too generic to justify a high-severity finding.
- *Verified:* all five previously-misclassified paths now classify correctly; django's false high
  finding is gone.

**F6 — robots.txt is now actually enforced on our own fetches.**
`site_inventory.py`, `engagement_scan.py`

- *Root cause:* the parser was correct and computed decisions for the AI user agents, but nothing
  gated our own crawling. The handout makes this an explicit guardrail and README line 62 claimed
  compliance we did not have.
- *Change:* added `SiteInventory.may_fetch()`, resolving against the `*` group (we are not a named
  agent) and enforcing same-origin. It gates both the page crawl and the engagement broken-link
  sampler. Declined URLs are recorded in `skipped_by_robots` as an audit trail, and
  `from_dict()` re-parses robots so a rehydrated inventory still gates follow-up fetches.
  robots.txt and the discovery files (`sitemap.xml`, `llms.txt`, `ai.txt`) stay permitted.
- *Verified empirically*, not just by reading: local server with `Disallow: /private` and
  `Disallow: /secret` for `User-agent: *`, homepage linking to both.
  Before — auditor fetched `/private/data` and `/secret/x`. After — `DISALLOWED paths fetched: NONE`.

**F7 — Template-level defects collapse into one finding instead of one per page.**
`engagement_scan.py`, `render_and_data_scan.py`, `freshness_and_consistency_scan.py`

- *Root cause:* fingerprints embedded the page path, so footer- and template-level issues repeated
  once per crawled page. mozilla.org shipped 5 identical "stale copyright" findings and 2 identical
  breadcrumb findings out of 11 total.
- *Change:* site-wide fingerprints for `missing-h1`, `multiple-h1`, `missing-breadcrumbs`,
  `few-internal-links`, `missing-title`, `missing-description`, `schema:syntax-error`,
  `schema:missing-required-fields` and `canvas-locked-content`; the existing dedupe merges their
  evidence so every affected URL is still listed. The copyright check was restructured to
  aggregate across pages and emit a single finding naming the affected pages and the count.
  Genuinely page-specific findings (missing Product/Offer on a given money page, missing CTA,
  render gap) keep per-path fingerprints.

---

### 2026-08-31 — Batch 2: honest evidence, and the two dead skills brought to life

**F8 — Removed the fabricated corroboration finding.**
`run_audit.py`, `corroboration_scorer.py`

- *Root cause:* the orchestrator built a fact list whose only source was flagged
  `is_brand_owned: True`, so `score_fact()` always returned `uncorroborated` and emitted evidence
  reading *"Searched external sources for claim ...; found 0 independent authoritative supporting
  sources."* No search was ever performed. This is the worst possible failure under a rubric that
  grades on evidence — a judge who checks one evidence string finds the tool asserting an
  observation it never made.
- *Change:* the orchestrator no longer calls `score_fact()` / `assess_collision_risk()` with
  invented inputs. Those functions are untouched and remain the *agent-driven* path, reachable
  through the skill's standalone CLI when real third-party search results are supplied.
- *Verified:* grepped all five regenerated reports for "Searched external sources" —
  **0 occurrences**.

**F9 — `trust-corroboration-graph` now reports what it can actually observe.**
`corroboration_scorer.py` — new `evaluate_identity_anchoring()`

- *Root cause:* the skill was inert in the composed path (collision check always called with an
  empty list), so `entity-disambiguation` could never fire and the skill contributed nothing.
- *Change:* new check answering the observable half of Appendix D — is there *any* machine-readable
  path from this site to an independent authority? Inspects Organization `sameAs` URIs and every
  outbound external link domain against an `AUTHORITY_DOMAINS` list (Wikidata, Wikipedia,
  Crunchbase, LinkedIn, GitHub, SEC, Companies House, …). Emits one finding when the count is zero,
  with evidence stating exactly what was counted. It never claims to have searched the web.
- *Verified:* fires on iana.org (no anchors); correctly stays silent on python.org, react.dev,
  mozilla.org and djangoproject.com, all of which link to GitHub or LinkedIn.

**F10 — `citation-simulator` now runs on every site instead of only when robots blocks the root.**
`generate_queries.py` — new `evaluate_answerability()`; `run_audit.py`

- *Root cause:* the skill was gated behind `if robots_blocked:` and then fed itself a **hardcoded**
  result dict — query string, `"classification": "omission"` and evidence sentence all literal.
  It contributed nothing on 4 of 5 sites, and README line 49 claimed the orchestrator "never
  invents or hardcodes findings" directly above that code.
- *Change:* deleted the hardcoded block. The skill now tests the last step of the Appendix-B loop
  deterministically and offline: given the pages actually crawled, could an assistant quote an
  answer to a natural question about this brand? Four probes — identity, offering, pricing,
  contact — checked against extracted schema types and page text. Findings are `likely-risk` /
  medium confidence because we sample a handful of pages, so absence is a strong signal rather
  than proof.
- *Guard against manufactured defects:* the pricing probe only fires on sites with a commercial
  surface (`product_pricing` page or Product/Offer/Service schema). Asking "how much does X cost?"
  of a docs site or a public agency is a manufactured defect, not a finding.

**F11 — The identity probe merges with the schema finding instead of double-reporting.**
`generate_queries.py`

- *Root cause:* F10's identity probe and crawl-render-audit's "Missing Organization schema" are the
  same root cause. Shipping both is exactly the padding the rubric penalises.
- *Change:* the identity probe reuses fingerprint `schema:root-organization-missing`, so the
  existing dedupe merges them into one finding carrying evidence from both skills.
- *Side benefit:* the merged finding now lists `source_skills: [citation-simulator,
  crawl-render-audit]` — two independent checks corroborating one root cause is a much better
  demonstration of composition than two separate findings.

**F12 — Brand name is no longer scraped from the page tagline.**
`site_inventory.py`

- *Root cause:* the ground-truth fallback took the `<title>` and split on `|`/`-`, producing brand
  names like `"Welcome to Python.org"`, `"Internet for people, not profit"` and
  `"The web framework for perfectionists with deadlines"`. These leaked into generated queries and
  finding titles.
- *Change:* resolution order is now Organization schema `name` → `og:site_name` → a `<title>` of
  four words or fewer → the domain label. Taglines can no longer win.
- *Verified:* `Python.org`, `React`, `Mozilla`, `Django Project`, `Iana`.

**Net result after batch 2** (findings per site, and every skill now contributing):

| Site | Before review | After batch 1 | After batch 2 |
|---|---|---|---|
| python.org | 8 (4 false high) | 3 | 5 |
| react.dev | 5 (1 false high) | 3 | 5 |
| mozilla.org | 11 (5 dup lows) | 4 | 7 |
| djangoproject.com | 11 (1 false high, 5 dup) | 3 | 4 |
| iana.org | 4 | — | 6 |

Counts rose from batch 1 because two previously-dead skills now contribute real findings.
Zero fabricated-evidence strings remain. All 21 tests pass.

---

### 2026-08-31 — Batch 3: documentation honesty, hygiene, regression cover

**F13 — Corrected six false claims in README.md and three in the SKILL.md files.**

| Claim | Reality | Now says |
|---|---|---|
| "parallelized pass" | zero concurrency in the repo | "bounded sequential pass ... gated by robots.txt" |
| "All 5 specialist skills consume the same cached snapshots" | three do; two get derived inputs | names which three read the cache and how the other two are fed |
| "orchestrator never invents or hardcodes findings" | it hardcoded a citation finding | true again after F8/F10, and states the boundary explicitly |
| "raw HTML vs rendered DOM" | no headless browser exists | "raw, non-JS-executed HTML -- what a non-rendering retrieval bot sees" |
| "respects robots.txt" | parsed but unenforced | enforced, names `may_fetch()` and `skipped_by_robots` |
| citation-simulator "runs the search-fetch-answer loop" | it did not | describes the deterministic answerability mode and the agent-supplied mode |

The mermaid diagram was drawing five arrows from the snapshot cache; it now shows the two
derived skills going through the orchestrator. `crawl-render-audit/SKILL.md` and
`citation-simulator/SKILL.md` and `trust-corroboration-graph/SKILL.md` had the same
rendered-DOM / live-search overclaims and were corrected to match what the code does.

**F14 — Added `license` and `allowed-tools` to all six SKILL.md frontmatter blocks.**
The handout's example includes `license` and asks skills to "declare any allowed-tools"; none
of the six had either. Scanning skills declare `Bash, Read`; the orchestrator adds `Write`;
`citation-simulator` and `trust-corroboration-graph` add `WebSearch, WebFetch` for their
agent-driven modes.

*Also fixed the test that was enforcing the omission:* `test_skill_frontmatter_and_manifest`
asserted the frontmatter key set was **exactly** `{name, description}`, which made adding the
requested fields a test failure. It now asserts required-keys-as-subset, rejects unrecognised
keys, and additionally checks `name` matches the marketplace id and folder name.

**F15 — Purged committed build artefacts and stale outputs from the submission.**
Added `.gitignore` (was absent). `git rm --cached` on 13 `.pyc` files across seven
`__pycache__/` directories, the seven stale root artefact JSONs, and the 88-byte
`package-lock.json` stub (there is no JS in this project). Repo root is now just
`Progress.md`, `README.md`, `marketplace.json`, `skills/`, `tests/`, `validation-runs/`.

Notably this removed the root `report.json`, which contained a
*"Missing machine-readable dateModified and datePublished metadata"* finding — something the
current code explicitly refuses to emit and the README lists as an eliminated false positive.
A judge comparing the two would have caught the contradiction.

**F16 — Regenerated `validation-runs/` from the current pipeline.**
Deleted the stale intermediate scan files and the old reports, including
`nasa-report.json` which shipped 0 findings and 0 proactive recommendations. Six sites now,
chosen for structural variety rather than tuned against: python.org, react.dev, mozilla.org,
djangoproject.com, iana.org, stripe.com. Added `RUNS.md` with runtimes and severity counts.

- All six validate against `report-schema.json` with real `jsonschema`.
- Fabricated-evidence sweep across all six: **0**.
- Slowest run 16.3s (stripe.com), well inside the 5-minute budget.
- stripe.com is a useful generalization check: correctly classified commercial, correctly
  flagged for missing Product/Offer schema, and correctly **silent** on the identity and
  contact probes, since Stripe does publish Organization schema and contact routes.

**F17 — Added `tests/test_regressions.py` (29 tests).**
One test per fixed bug so none of these can silently return: gzip-by-header and
gzip-by-magic-bytes, case-insensitive header lookup, the unreadable-content gate, copyright
ranges with both hyphen and en-dash, single site-wide copyright finding, `since`-prose
rejection with founding verbs still matching, all four page-purpose substring traps,
robots enforcement including the inventory round-trip, evidence-honesty assertions
(including an explicit `assertNotIn("Searched external sources", evidence)`), the
non-commercial pricing-probe guard, and brand-name resolution order.

Suite is now **50 tests, all passing**, still stdlib-only.

---

## Open

Ranked by rubric impact.

### Remaining

20. **Repo identity is split.** Directory is `citesense`, manifest name is
    `brand-ai-readiness-audit`, README title matches the manifest. The handout says to zip the
    marketplace root, so the *directory name is what judges see first*. Left alone deliberately —
    renaming the repo is the team's call, not a silent change. Pick one and make it consistent.

Items 18, 19, 21 and 22 are closed — see batch 4 above.

### Known limitations (deliberate, documented rather than hidden)

- **No JS rendering.** The audit reads raw HTML only. This is the harsher and more realistic case
  for non-rendering retrieval bots, and it is now stated accurately in the README and SKILL.md
  rather than claimed as rendered-DOM analysis. A site whose facts appear only after hydration
  will be reported as a render gap, which is the correct call for AI discoverability.
- **English-biased text heuristics.** Price detection, CTA phrases, contact affordances and
  account affordances are English keyword sets. Where this could manufacture a finding on a
  non-English page, the check is keyed on URL structure instead (see F19). Broader language
  coverage is the obvious next improvement if there is time.
- **Sampled crawl.** 5 pages by default. Findings that depend on absence across the site are
  emitted as `likely-risk` with medium confidence, never as `confirmed`.
- **Agent-supplied modes are not exercised by the deterministic pipeline.** `score_fact()`,
  `assess_collision_risk()` and `evaluate_citation_simulation()` need real third-party search
  results and are reachable only through the standalone skill CLIs. This is intentional: the
  alternative is inventing the inputs, which is the bug F8 removed.

### 2026-09-01 — Batch 5: correctness cleanup and the last open item

**F23 — A redirected page was stored twice, inflating every page count.**
`site_inventory.py`, `engagement_scan.py`

- *Root cause:* `crawl_site()` stored each snapshot under both the requested URL and the final
  URL after redirects. On python.org, `/psf/` and `/psf-landing/` held the same snapshot, so a
  5-page crawl reported `pages_crawled: 6`. Every aggregate check that says "across N crawled
  pages" — the answerability probes, the site-level engagement checks — was quoting an inflated
  number in its evidence, and evaluators processed the same page twice.
- *Change:* snapshots are stored once, keyed by final URL, via new `store_page()`. Redirects are
  recorded in `url_aliases`, and `knows_url()` recognises both sides so candidate selection and
  the broken-link sampler still skip already-fetched pages. Aliases survive the inventory
  round-trip.
- *Verified:* python.org now reports 5 pages for 5 real pages, 1 alias, 0 duplicate snapshots.

**F24 — Removed dead imports and a dead assignment from the orchestrator.**
`run_audit.py`

Six unused imports (`build_queries`, `evaluate_citation_simulation`, `score_fact`,
`assess_collision_risk`, `generate_trust_findings`, `assign_ids_and_validate`) and the unused
`queries = build_queries(gt)` line. Worse than untidy: importing the agent-supplied functions
into the orchestrator implied it calls them, which is exactly the confusion F8 existed to end.
Replaced with a comment saying where they live and why they are not invoked here.

**F25 — Category sets have a single source of truth.**
`compose_report.py`

`DISCOVERABILITY_CATEGORIES` and `ENGAGEMENT_CATEGORIES` were defined independently in both
`models.py` and `compose_report.py`. They happened to agree, but a drift would silently mis-split
the summary counts with no test catching it. `compose_report` now imports them. Added
`ContractDriftTests` asserting the schema enum equals `VALID_CATEGORIES`, that every category is
classified into exactly one half, and that both modules share the same set objects.

**F26 — `report-schema.json` now documents the contract the code actually enforces.**
`assign_ids_and_validate()` rejects any finding whose `suggested_action` lacks `how_to_fix`, but
the schema only required `summary` and `priority` — the published contract was weaker than
reality. Schema now requires `how_to_fix`, and describes the `status`, `confidence`, `impact`,
`fingerprint` and `source_skills` fields findings have always carried. All six validation
reports still validate.

**F27 — Fixed a false positive in my own batch-4 check.** *Caught on stripe.com.*
The pricing-route guard from F19 matched word tokens anywhere in the path, so
`stripe.com/in/newsroom/news/stripe-openai-instant-checkout` matched `checkout` inside its slug
and was charged a **high** "pricing page states no price". It now matches whole path *segments*
and additionally requires `page_purpose == "product_pricing"`, which already resolves editorial
routes ahead of commercial ones. Stripe back to 1 high, legitimate. `/in/pricing` still matches,
so localized pricing routes are unaffected.

*Worth noting for the log:* this is the second false positive introduced by a check written to
close an open item, and both were caught only by running against real sites rather than by the
unit tests. Re-run the validation set after any detection change — `tests/` alone will not catch
this class of bug.

**Item 20 closed — marketplace identity unified as `citesense`.**
The directory was `citesense`, the manifest said `brand-ai-readiness-audit`, and the README title
followed the manifest. Since the zip's root directory is what a judge sees first and that is the
repository name, the manifest was aligned to the repo rather than the other way round:
`marketplace.json` name is now `citesense`, the README is titled **CiteSense**, and the
descriptive phrase moved into the manifest `description` where it belongs. Zip root, manifest and
docs now agree. Flip it the other way by renaming the repo and setting the manifest name back if
the team prefers the descriptive identity.

---

### Note on test sites and generalization

The handout provides **no example sites** — verified by extracting its full text: the only
domains anywhere in it are `agentskills.io`, `schema.org` and `example.com` (a placeholder in the
sample report schema). It states plainly:

> "We won't hand you a list of test sites... We won't ask which sites you studied, and none of
> them are used in grading... Design for patterns, not fit-to-examples."

The six sites in `validation-runs/` are our own field-research choices, spanning different
structural shapes. They are **not** referenced by any detection logic. Audited on 2026-08-31:

- No real site name appears in any check, threshold, regex or branch in `skills/`.
- Two source **comments** name python.org (unsolicited-gzip CDN behaviour) and a Mozilla-style
  tagline. These document *why* a fix exists and are evidence of the field research the handout
  asks for — they do not affect behaviour. Keep them.
- `AUTHORITY_DOMAINS` in `corroboration_scorer.py` lists Wikidata/Wikipedia/Crunchbase/LinkedIn/
  SEC/Companies House etc. This is a **category** of independent authority sources, applicable to
  any brand anywhere — not a list of sites we tested against.
- All tests now use reserved placeholder domains (`.test`, `example.com`). The one real hostname
  that had crept into `test_regressions.py` was genericized to `acme.test`.

Every fix in this log is transport-, parser- or logic-level and applies to any site: gzip
handling, copyright year ranges, founding-verb precision, whole-token URL classification,
robots enforcement, evidence honesty. None encode a characteristic of a specific website.

### P3 — Nice to have

21. `crawl-render-audit/references/severity-guide.md` still describes a
    `js_dependency_ratio > 0.35` threshold that no longer exists in the code (the render-gap
    check is a word-count/empty-shell test). Align the doc with the implementation.

22. No `CONTRIBUTING`-style note on how to add a new check. Given that teammates and their agents
    are working in parallel, a short "how to add a CandidateFinding without creating a false
    positive" section would prevent drift — the rules are currently implicit in the code.

---

## Verified-good (don't "fix" these)

- Report schema compliance: four live reports validated against `report-schema.json` with real
  `jsonschema`. All pass.
- All five documented standalone CLI commands in the README run and exit 0.
- Redirect handling (5 hops) and 4xx/5xx vs. timeout distinction work as documented.
- The "missing XML sitemap" findings are **true positives** — python.org, mozilla.org and
  react.dev all genuinely 404 on `/sitemap.xml` with no `Sitemap:` directive in robots.txt.
- The robots.txt *parser* (longest-match, Allow-wins ties) is correct.
