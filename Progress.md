# Progress Log — CiteSense

Working log for the Adobe University Hackathon 2026 Round 3 submission.
**Audience: teammates and their AI coding agents.** Read this before touching the repo.

---

## How to use this file

- Every fix gets an entry under **Fixed**, with the root cause, the change, and how it was verified.
- Anything known-broken but not yet fixed lives under **Open**, ranked by impact on the rubric.
- If you fix something, move it from **Open** to **Fixed** and record your verification command.
- Don't claim a fix without a reproduction. Every entry below has one.

## Current status — 2026-09-07

| | |
|---|---|
| Tests | **104 passing**, stdlib only |
| Fixes landed | **F1–F35** across seven batches |
| False positives removed | 4 high on python.org, 1 high on react.dev, 1 high on django, 10 duplicate lows |
| Fabricated evidence strings | **0** (swept across all six validation reports) |
| Skills contributing findings | **6 of 6** (was 4 of 6) |
| Discoverability:engagement | ~2:1 (was ~5:1) |
| robots.txt | **enforced**, verified against a local disallow server |
| Schema compliance | all six validation reports validate with real `jsonschema` |
| Slowest audit | 21.1s (stripe.com) against a 5-minute budget |
| Proactive recs | 3–6 per site (was 0 on 2 of 6) |
| Validation set | 10 sites, two sets: well-built and niche |
| Still open | nothing tracked — see Known limitations |
| Merged from upstream | MaiCoderHoon's F-008–F-013 post-report tooling (2026-09-07) |

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

### 2026-08-31 — Batch 4: closing open items 18, 19, 21, 22

*Log entry reconstructed 2026-09-07 from commit `dd2234e`; the code shipped at the time but this
section was lost when a later edit re-anchored on the wrong heading.*

**F18 — `alt=""` is no longer conflated with a missing alt attribute.** `site_inventory.py`
`has_alt` was `bool(alt)`, so a correctly-marked decorative image was indistinguishable from an
unlabelled one. Any check built on that field would have fired on nearly every well-built site.
Snapshots now carry `alt_attr_present` and `decorative`.

**F19 — Image-locked facts detected (Appendix C).** `render_and_data_scan.py`
The `images` data was collected into every snapshot and used by nothing. Two checks now use it:
≥5 images with no alt attribute at all (decorative excluded), and an explicit pricing route
carrying images but no price in text and no `Offer` schema. The latter was scoped down after
firing on `mozilla.org/de/products/`, a free-product catalogue whose German copy the
English-only price test could not read.

**F20 — Engagement widened; `personalization-readiness` finally emits.** `engagement_scan.py`
That category was declared in `models.py` and the schema enum and produced by nothing. Three
site-level checks added, all targeting the cold-arrival case: deep pages that never name the
brand, missing site search, and no returning-visitor affordance (emitted `proactive`, since a
static crawl cannot observe personalization that only activates for a signed-in session).

**F21 — `severity-guide.md` realigned.** Removed the `js_dependency_ratio > 0.35` threshold,
which no longer exists in the code.

**F22 — Added `references/adding-checks.md`.** House rules for adding detection logic without
creating false positives. Every rule in it was learned from a check that shipped and was wrong.

---

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

### 2026-09-01 — Batch 6: re-grounded against September 2026 standards

Researched current practice before changing anything; sources and the finding-to-evidence mapping
are recorded in `skills/audit-orchestrator/references/ai-visibility-standards-2026.md`. Three of
the four findings below changed **detection behaviour**, not just wording.

**F28 — AI crawlers are now scored by consequence class, not treated alike.**
`audit_common.py`, `crawlability_check.py`

- *What the research changed:* AI user agents fall into three classes with completely different
  consequences. **Training** crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot,
  Applebot-Extended, Meta-ExternalAgent) harvest for model training — blocking them costs **no
  citations**. **Search-index** crawlers (OAI-SearchBot, Claude-SearchBot, PerplexityBot) build the
  retrieval indexes answers are assembled from. **User-triggered** fetchers (ChatGPT-User,
  Claude-User, Perplexity-User) load a page when a user is literally asking about it.
- *The false positive this removes:* a publisher blocking GPTBot while allowing OAI-SearchBot has
  made a coherent licensing choice and remains fully citable. We were reporting that as
  **critical**. Now: critical only when a citation-critical agent is blocked; `low` +
  `proactive` when only training crawlers are, with the stance acknowledged as legitimate.
- *Also corrected the agent list:* added `Claude-User`, `Claude-SearchBot` and `Meta-ExternalAgent`;
  `Claude-Web` and `anthropic-ai` are legacy names.

**F29 — Proactive recommendations rebuilt as an evidence-ranked engine.** *Closes the rubric gap.*
New `skills/audit-orchestrator/scripts/proactive_recommendations.py`

- *The gap:* only two recommendations existed, both conditional. react.dev and stripe.com received
  **zero**, scoring nothing on a named rubric criterion.
- *Now:* nine observation-gated recommendations, capped at 6 and ordered strongest-evidence-first.
  FAQPage for existing Q&A content (`high` — highest-leverage schema type for citation, since its
  Q&A shape matches how retrieval chunks and lifts answers); third-party entity anchoring (`high` —
  only ~11% domain overlap between ChatGPT and Perplexity citations, so on-site work alone caps
  reach); answer-first content restructuring; Article schema with author/dateModified; WebSite +
  SearchAction; BreadcrumbList; explicit AI usage terms via Content Signals Policy or RSL; an
  agent-facing NLWeb/MCP endpoint; and llms.txt.
- *Result:* every validation site now receives 3–6. stripe.com correctly receives only 3, all
  `low` — it already has the schema coverage and third-party presence the high-priority items ask
  for. Fewer recommendations for a better site is the right behaviour, not a gap.

**F30 — llms.txt recommendation corrected to match the evidence.**
We were recommending it as a straightforward win. The 2026 data says otherwise: across a monitored
window of 500M+ AI bot visits only **408** requests targeted `/llms.txt`, major crawlers skip it
and read HTML directly, and **Google stated in June 2026 that it has no effect** on Search or AI
Overviews. It is now `low` priority with that evidence stated in the rationale, and its absence is
explicitly never a finding. Recommending it as established practice would have been the same class
of error as the fabricated evidence in F8 — asserting more than we can support.

**F31 — Entrypoint SKILL.md corrected.** *Closes the second item from the status review.*
`skills/audit-orchestrator/SKILL.md` is the skill judges invoke, and it had gone stale while the
three specialist SKILL.md files were fixed in F13. It described `citation-simulator` as running a
"simulated search loop" and `trust-corroboration-graph` as evaluating "external corroboration and
entity disambiguation risk" — both now agent-supplied modes. It claimed "2-4 proactive
recommendations" when 2 were possible and 0 were often produced, and its robots.txt guardrail
described advisory behaviour rather than the enforcement added in F6. All corrected, plus a
References section pointing at the schema, the standards evidence, and the check-authoring rules.

**New reference: `references/ai-visibility-standards-2026.md`.** The evidence basis for every
severity and priority in the report — crawler taxonomy, structured-data leverage, off-site presence,
content chunking, and what is emerging but not yet load-bearing (Content Signals Policy, RSL, NLWeb,
UCP) — with sources and a table mapping each finding and recommendation back to its justification.
The handout asks for field research distilled into the skill; this is where ours is written down.

**Tests: 93 passing** (added `tests/test_proactive_and_crawler_class.py`, 14 tests). Validation set
regenerated: 6/6 schema-valid, 0 fabricated evidence strings, **0 reports with zero proactive
recommendations**.

---

### 2026-09-01 — Batch 7: tested against small real sites, found two serious bugs

The validation set was six large, well-built engineering sites. That turned out to be the
opposite of the scenario this marketplace exists to diagnose, and it was hiding real defects.
Four niche sites were added as **Set B** (`validation-runs/RUNS.md`). Both bugs below were
invisible in Set A and obvious in Set B.

**F32 — Any site whose apex redirects to www was reduced to a one-page crawl.** *Regression I introduced in F6.*
`site_inventory.py`

- *Root cause:* the same-site gate added with robots enforcement compared each link against
  `self.origin`, which was recorded from the **seed URL before redirects**. `fedkiit.com`
  redirects to `www.fedkiit.com`, so origin stayed on the apex while every page and link lived on
  www — and `may_fetch()` refused all 9 internal links as off-origin. The crawl stopped at the
  homepage.
- *Why Set A never caught it:* all six were seeded with their already-final hostname
  (`www.python.org`, `www.mozilla.org`, …) or do not redirect. The regression was invisible by
  construction.
- *Change:* the inventory adopts the origin the seed actually resolved to, and a new
  `same_site()` treats apex and www as one host. Sitemap URL filtering uses it too — a sitemap
  listing `www.` URLs against an apex origin was previously discarded whole, which is why three
  sites reported `discovered_url_count: 0` against a live sitemap.
- *Verified:* fedkiit.com goes from 1 page to 5, and surfaces a **high-severity render gap** that
  had been completely invisible. Robots enforcement still holds across the www boundary.

**F33 — Compact client-rendered shells escaped render-gap detection.**
`site_inventory.py`, `render_and_data_scan.py`

- *Root cause:* the check required `words < 30 and len(raw_html) > 1000`. `faktcheck.fedkiit.com`
  serves a 5-word shell in under 1KB of HTML, so the single most important problem with the page
  was not reported at all.
- *Change:* the shell test is now `words < 30 and (no h1 or html > 1500)`, set once in
  `analyze_page_html` as a `render_gap` flag so every skill agrees. The h1 clause matters: a short
  page that still carries a heading and its facts is complete, just brief — an adversarial test
  in the existing suite caught an earlier, blunter threshold flagging exactly that case.

**F34 — A shell page produced eleven findings for one root cause.**
`render_and_data_scan.py`, `engagement_scan.py`

kforum.me previously returned 11 findings: render gap, missing h1, no CTA, isolated page, missing
meta description, missing Organization schema, and so on. Every one after the first is a symptom
of the page being an empty shell. Page-level checks are now suppressed on `render_gap` pages and
the render-gap evidence says so explicitly. kforum.me: 11 findings → 7, led by the actual cause.

**F35 — CTA finding no longer calls every homepage "commercial".**
A fact-checking tool and a student forum were both reported as a "Commercial landing page". Title
is now purpose-aware.

**Set B results.** All 10 reports schema-valid, 0 fabricated evidence, 0 with zero proactive recs.
No regressions on Set A. Findings on the niche sites are independently verified where checkable —
`fedkiit.com/Manifesto` really does return 404.

**Known blind spot, now documented rather than assumed.** `bbsrgotlaytent.live` returns **zero**
web search results yet gets the cleanest report of all ten (4 findings, none high). That is not a
broken check: its on-site hygiene genuinely is good. Its problem is entirely off-site, and the
deterministic pipeline can see the absence of authority links but cannot see absence from search
itself. The `corroboration` finding names the right root cause; confirming it needs the
agent-supplied `citation-simulator` mode. This is the strongest argument for running the
marketplace under an agent with web-search tools rather than only through the CLI.

**On method.** Both bugs came from testing on sites that resemble the grading target, not from
more unit tests. Set A measured precision; only Set B measured recall. Keep both.

---

### Note on test sites and generalization

The handout provides **no example sites** — verified by extracting its full text: the only
domains anywhere in it are `agentskills.io`, `schema.org` and `example.com` (a placeholder in the
sample report schema). It states plainly:

> "We won't hand you a list of test sites... We won't ask which sites you studied, and none of
> them are used in grading... Design for patterns, not fit-to-examples."

The ten sites in `validation-runs/` are our own field-research choices, spanning different
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

---

## Post-report tooling — MaiCoderHoon (upstream, merged 2026-09-07)

Written independently on the upstream branch while the detection work below was in progress.
**Two numbering schemes exist in this file and they are not related:** entries below this heading
use `F-0NN` and cover post-report tooling; entries in the detection log use `F1`-`F35` and cover
crawl, detection and evidence correctness. Do not renumber either — commit messages reference both.

The "reconstructed F-001 – F-007" table below was written before the detection work landed, so it
describes the pipeline as it stood at commit `74cb328`. Several of those descriptions are now
superseded — notably F-004 (false-positive elimination) and F-005/F-006, whose citation and
corroboration behaviour changed substantially in batches 2 and 6 of the detection log.

## Previously shipped (reconstructed from commits `3003fed`, `74cb328`)

| ID | Feature | Where |
|---|---|---|
| F-001 | Shared single-pass `SiteInventory` crawler consumed by all five specialist skills | `skills/crawl-render-audit/scripts/site_inventory.py` |
| F-002 | Structured `CandidateFinding` / `EvidenceVerification` contract (`status` / `confidence` / `impact` / `fingerprint`) | `skills/crawl-render-audit/scripts/models.py` |
| F-003 | Root-cause deduplication, severity elevation and `F-NNN` ID assignment | `skills/audit-orchestrator/scripts/compose_report.py` |
| F-004 | False-positive elimination (redirect-aware links, `dateModified` not a defect, depth-gated breadcrumbs, JS-use not a defect) | all five specialist skills |
| F-005 | Citation-simulation classification (omission / misattribution / staleness / contradiction) | `skills/citation-simulator/scripts/generate_queries.py` |
| F-006 | External corroboration scoring and entity-collision risk | `skills/trust-corroboration-graph/scripts/corroboration_scorer.py` |
| F-007 | End-to-end orchestrator CLI and report schema validation | `skills/audit-orchestrator/scripts/run_audit.py` |

---

## F-008 — HTML report dashboard

**Root cause.** `report.json` was the only deliverable. It is the right machine format, but
a reviewer (or a judge) reading a 7-finding, ~10 KB JSON document has to hold the severity
ordering, the discoverability/engagement split and the evidence strings in their head. The
report had no human-facing view, and adding one via any charting or templating library
would have broken the stdlib-only / small-zip constraint.

**Change.** New `skills/audit-orchestrator/scripts/render_dashboard.py`. Reads a
`report.json` and emits one self-contained HTML file — inline `<style>` and `<script>`, no
frameworks, no build step, no external requests (verified in test: the only absolute URL in
the output is the audited site's own header link). Renders:

- header with site, `audited_at`, a severity badge row, and the AI-Citability Score (F-011)
  with its arithmetic spelled out when present;
- a two-bar discoverability-vs-engagement comparison driven by
  `summary.discoverability_findings` / `summary.engagement_findings`;
- findings grouped by severity, critical first, each with title, category, status,
  confidence, impact, source skills, evidence, and `suggested_action.how_to_fix`. Evidence
  over 220 characters collapses into a `<details>` disclosure; a `fix_snippet` (F-009)
  renders as a collapsible, HTML-escaped code block;
- a visually distinct **Proactive Recommendations** section (dashed green panel, no
  severity colouring) that states in the page that these are opportunities, not defects.

Every value is escaped with `html.escape(..., quote=True)`, and optional blocks are skipped
rather than defaulted: no `proactive_recommendations` ⇒ no section; no `citability_score` ⇒
no score tile; no findings ⇒ an explicit "No findings recorded" note. Nothing is invented to
fill a gap.

CLI: `python render_dashboard.py report.json --output dashboard.html` (stdout if `--output`
is omitted).

**How verified.** `tests/test_render_dashboard.py` (15 tests). Well-formedness is checked by
parsing the output with `html.parser.HTMLParser` and asserting the tag stack closes empty —
not by string matching. Asserts the site name, timestamp and every finding title appear;
that the proactive section is present when the key is present and *absent* (no error) when
it is missing or empty; that a report with zero findings still renders; that a
`<img src=x onerror=...>` title comes out escaped; that the score tile appears only when
`summary.citability_score` exists; and an end-to-end subprocess run of the CLI writing a
real file. Also smoke-run against the repository's own `report.json`
(7 findings, 3 recommendations, 17 KB output).

---

## F-009 — Auto-generated JSON-LD fix snippets

**Root cause.** A structured-data finding told the user *what* was missing and described the
fix in prose, but left them to hand-write the JSON-LD. The obvious shortcut — shipping a
generic template — would have meant printing invented values (a placeholder brand name, a
made-up founding year) next to real findings, which is exactly the fabrication the project
forbids.

**Change.** New `skills/audit-orchestrator/scripts/fix_snippets.py`. For findings in
category `structured-data` that express *absence* of markup, it generates a ready-to-paste
`<script type="application/ld+json">` block for `Organization`, `Product`, `FAQPage`,
`Article` or `BreadcrumbList`, populated from data the crawl actually observed:

| Source | Fields it populates |
|---|---|
| `ground_truth` | `name` / `brand`, `sameAs`, `foundingDate`, `telephone`, `email`, `description` |
| cached page snapshot | `Product`/`Article` name from the observed H1 or title, `description` from the observed meta description, `datePublished` from observed date metadata, `FAQPage` questions lifted **verbatim** from headings ending in `?` |
| the finding's own URL | `url`, and the full `BreadcrumbList` trail derived from the real path segments |

Fields with no observed value are emitted as explicit `REPLACE_WITH_...` markers
(`REPLACE_WITH_YOUR_LOGO_URL`, `REPLACE_WITH_PRICE_AMOUNT`, …) so a user can never mistake
a gap for a fact.

A snippet is emitted **only** when both gates pass, so a placeholder-heavy template is never
presented as a fix:

1. every *identifying* field for the type carries an observed value (Organization needs a
   real name **and** URL **and** at least one further observed fact; Product/Article need a
   real name from a page snapshot; FAQPage needs ≥1 real question; BreadcrumbList needs ≥2
   real crumbs), and
2. real values ≥ placeholder values across the whole snippet.

Otherwise `generate_fix_snippet` returns `None` and the finding is left untouched.

Wiring: `compose_report.build_final_report` now accepts `ground_truth` / `pages` and calls
`attach_fix_snippets` on the validated findings, so snippets appear automatically on every
composed report. `run_audit.py` passes `inventory.ground_truth` and `inventory.pages`
through; the standalone `compose_report.py merge` CLI gained `--inventory`, which accepts
either a saved `SiteInventory` JSON or a bare `ground_truth` object. With neither, no
snippets are generated — the behaviour degrades to exactly the previous output.

Schema: `suggested_action.fix_snippet` added to `references/report-schema.json` as an
**optional** string property. No existing property was removed, and
`suggested_action.required` is unchanged (`["summary", "priority"]`).

**How verified.** `tests/test_fix_snippets.py` (13 tests). Asserts the generated block parses
as valid JSON and carries the real brand name (`"Acme Robotics"`, not a placeholder) when
ground truth supplies it; that **no** snippet is produced when ground truth is sparse
(name + URL only) or absent; that non-`structured-data` findings, malformed-JSON-LD *repair*
findings, and `meta:missing-title` / `meta:missing-description` findings are never given an
insert snippet; that Product is suppressed without a page snapshot rather than inventing a
product name; that FAQPage questions match the page headings verbatim and exclude
non-questions; that the BreadcrumbList trail is derived from the real URL path; that
attachment is idempotent; and that `build_final_report` attaches snippets with ground truth
and omits them without it. Additionally smoke-run through the real merge CLI against
`crawl_findings.json`, producing a Mozilla `Organization` block with real
`name`/`foundingDate`/`sameAs` and only `logo` marked `REPLACE_WITH_`.

---

## F-010 — Report comparison / diff tool

**Root cause.** Nothing in the pipeline could answer "did the fix work?". Two runs of the
same site produced two independent reports whose `F-NNN` IDs are positional — they are
reassigned on every compose, so `F-003` in a before-report and `F-003` in an after-report
are frequently different findings. Comparing by ID would have been actively misleading.

**Change.** New `skills/audit-orchestrator/scripts/compare_reports.py`. Matches findings
across two reports by the stable `fingerprint`, falling back to
`(category, normalized_title)` when either side lacks one — reusing
`compose_report.normalize_title`, so cross-report matching behaves identically to the
existing dedupe. A secondary title index also catches the case where a finding gained or
lost its fingerprint between runs. Output buckets:

- `resolved` — present in A, gone from B;
- `new` — present in B, absent from A;
- `unchanged` — present in both, annotated with `previous_severity`, `severity_changed`,
  and a `severity_change` direction of `improved` / `worsened`;
- `score_delta` = `Σ weights(A) − Σ weights(B)` on a flat `critical=4 / high=3 / medium=2 /
  low=1` ladder, so positive means net improvement. Kept deliberately distinct from the
  F-011 citability score (different question, different scale — documented in
  `references/citability-score.md`).
- `citability_score_delta` — `after − before`, only when *both* reports carry the score;
  `null` otherwise rather than a guess.

CLI: `python compare_reports.py before.json after.json --output diff.json`.

**How verified.** `tests/test_compare_reports.py` (17 tests). Two hand-built fixture reports
where each finding's destination bucket is known by construction: one kept, one fixed, one
downgraded critical→medium, one regression. Asserts the exact contents of all three buckets,
the `improved` / `worsened` direction labels, `score_delta == 4` from the hand-computed
`9 − 5`, zero delta for a report compared against itself, full positive delta when
everything is resolved, the fingerprint-less title fallback (including that the same title
in a *different* category does **not** match), one-sided fingerprints, the
`citability_score_delta` including its `None` case, and a subprocess run of the CLI writing
`diff.json`. Also smoke-run on two real validation reports.

---

## F-011 — AI-Citability Score

**Root cause.** The report gave severity counts but no single answer to "how bad is this,
overall?", which is the first thing a reviewer asks and the only thing that is comparable
between two sites or two points in time. The risk with any such number is that it becomes a
black box — a judge asking "why is this 64?" deserves arithmetic, not a model.

**Change.** New `skills/audit-orchestrator/scripts/scored.py` — kept out of
`compose_report.py`, matching the existing one-module-per-concern layout in
`skills/audit-orchestrator/scripts/`. Computes:

```
score = clamp(0, 100, 100 − Σ SEVERITY_PENALTY[severity] + corroboration_credit)
        critical 25 · high 12 · medium 5 · low 2
        credit = min(2 × strong-corroborated facts, 6)
```

`compute_citability_score()` returns the full breakdown (`base`, `penalty`,
`penalty_by_severity`, `corroboration_credit`, `counted_findings`); `annotate_report()`
writes just the integer to `summary.citability_score`, and `build_final_report` calls it on
every composed report. `python scored.py report.json --explain` prints the arithmetic for
any existing report.

Two deliberate restraints, both to avoid fabricated inputs:

- Corroboration credit is read **only** from signals genuinely recorded in the report
  (`summary.corroboration_strengths` or `findings[].evidence_details.corroboration_strength`).
  A report carrying neither gets 0 credit, not an estimate — so today the score is in
  practice `100 − penalty`.
- **Proactive recommendation count earns no credit at all.** Those entries describe what the
  *auditor* suggested, not what the *site* did; crediting them would make the score rise
  because we wrote more advice, measuring our output rather than the site's readiness.
  Rationale recorded in the reference doc so the omission is a documented decision rather
  than an oversight.

A finding with an unrecognized `severity` contributes 0 rather than a guessed weight.

Schema: `summary.citability_score` added to `references/report-schema.json` as an
**optional** integer (0-100). `summary.required` is unchanged.

Documentation: new `skills/audit-orchestrator/references/citability-score.md` — the formula,
a worked example reproducing the repo's own `report.json` score of 64, per-severity weight
justification tied back to `crawl-render-audit/references/severity-guide.md`, the reasoning
behind both restraints above, the guaranteed properties, and a table distinguishing
`citability_score` from `compare_reports.score_delta`.

**How verified.** `tests/test_citability_score.py` (14 tests). Pins **determinism** (ten
evaluations of the same report yield one distinct value) and **monotonicity** (adding a
critical finding never increases the score, checked across a growing run; every severity
strictly lowers it; at the 0 floor it stays at 0 rather than going negative). Also asserts
the documented arithmetic `100 − (25+12+5+2) = 56`, that a clean report scores 100, that no
corroboration signal means zero credit, that credit is capped at 6 and readable from both
recorded locations, that proactive recommendations do not move the score, that an unknown
severity contributes nothing, and that `build_final_report` attaches the score. Verified
against the real `report.json`: `penalty 36 → score 64`, matching the worked example in the
reference doc.

---

## F-012 — Post-review hardening of the four new CLIs

**Root cause.** A review pass exercised the new scripts against the real
`validation-runs/` reports and deliberately hostile inputs, and found four defects that the
feature tests had not covered because they all exercised the *happy* path:

1. `render_dashboard.py --output missing/dir/x.html` died with a raw `FileNotFoundError`
   traceback instead of creating the directory.
2. All three CLIs surfaced a bare `json.decoder.JSONDecodeError` traceback on a malformed
   report, with no indication of *which* file was bad.
3. `fix_snippets.py` had no CLI at all. Running it exited 0 with **no output**, which is the
   worst possible answer: indistinguishable from "there is nothing to fix". Because
   `report.json` carries no `ground_truth`, the module's correct answer for a bare report is
   "cannot populate", and that needed to be *said*, not implied by silence.
4. `compare_reports.py` silently diffed two *different sites* (verified: python.org vs
   react.dev produced a confident `score_delta: 30`), presenting a site change as a fix.

**Change.**

- New `skills/audit-orchestrator/scripts/report_io.py` — shared `load_report` / `write_text`
  / `fail` helpers. Imports nothing else in the repo, so every module can depend on it
  without a cycle (`compose_report` → `scored`, so the helpers could not live there).
  Converts `FileNotFoundError` / `JSONDecodeError` / `UnicodeDecodeError` / non-object JSON
  into a one-line `error: ...` on stderr naming the file and the parse position, exit 1.
  `write_text` creates parent directories with `os.makedirs(..., exist_ok=True)`.
- `render_dashboard.py`, `compare_reports.py` and `scored.py` now route all file I/O through
  it.
- `fix_snippets.py` gained a CLI plus a public `explain_fix_snippet()` that returns the
  decision **and its reason** — `"no ground_truth supplied -- pass --inventory ..."`,
  `"no cached page snapshot for <url>; refusing to invent a Product name"`, or on success
  `"4 real values, 1 marked placeholder"`. Suppression is now visibly a refusal to guess.
- `compare_reports.py` output gained `same_site` (origin comparison, trailing-slash
  tolerant) and `summary.no_changes`; the CLI prints a stderr warning when the two reports
  name different sites. Both are additive — no existing key changed meaning.

No detection logic and no scoring formula changed; this is entirely input/output robustness.

**How verified.** New `tests/test_report_io.py` (12 tests) covers the helpers directly and
drives **all four CLIs** as subprocesses, asserting exit code 1, an `error:` line, and
crucially `assertNotIn("Traceback", stderr)` for missing and malformed inputs; plus that
`--output` into a missing directory now succeeds for both writers, and the cross-site
warning fires only when sites actually differ. `tests/test_fix_snippets.py` gained 7 tests
for `explain_fix_snippet` and the new CLI (including that it emits nothing *and says why*
without `--inventory`, emits a real snippet with one, and accepts a bare `ground_truth`
object). `tests/test_compare_reports.py` gained 4 tests for `same_site` / `no_changes`.
`tests/test_citability_score.py` gained a test pinning the **worked example printed in
`references/citability-score.md`** (1 high + 4 medium + 2 low ⇒ penalty 36 ⇒ score 64), which
previously nothing enforced — the doc could have drifted from the code undetected.

Re-verified by hand after the fix: bad path, malformed JSON, non-object JSON, and
directory-creating `--output` all behave correctly across every CLI; `fix_snippets.py`
against `validation-runs/mozilla-report.json` with a real ground-truth file emits valid
JSON-LD carrying `"name": "Mozilla"`, `"foundingDate": "1998"` and the real Wikipedia
`sameAs`, with only `logo`, `price` and `priceCurrency` marked `REPLACE_WITH_`.

---

## F-013 — `impact` documented in the schema

**Root cause.** Every finding carries an `impact` field: `models.py` defaults it to
`severity` (`models.py:97`, `models.py:168`), `compose_report.py` elevates it on dedupe and
uses it as the secondary sort key (`compose_report.py:169`). But it appeared nowhere in
`references/report-schema.json`, so a reviewer reading the schema next to a real report
found a field the contract never mentions — and no specialist skill currently supplies a
distinct value, so in practice `impact == severity` on every finding of every report
(verified on a fresh python.org run: 9 high / 5 medium / 3 low, identical both ways).
Undocumented and always-redundant is the combination that reads as an oversight.

**Change.** `impact` added to the findings item schema as an **optional** string with the
same four-value enum as `severity`, immediately after it, with a description stating that it
mirrors `severity` unless a skill overrides it and that consumers may treat it as equal when
absent. Nothing else changed: `findings.items.required` is still
`["id", "title", "severity", "evidence", "suggested_action"]`, no property was removed or
made stricter, and no code path was touched. The schema has no `additionalProperties: false`,
so this is purely documentation catching up to behaviour — previously-valid reports stay
valid and the emitted output is byte-identical.

**How verified.** Schema reparsed and `required` asserted unchanged. Full suite re-run
(104 tests, OK) — including `run_audit.py`'s own schema validation, which composes and
validates a report against this file. Re-ran the live python.org audit end to end after the
edit and confirmed the report still validates and the findings are unchanged.

---

## Verification for this batch

```
python -m unittest discover -s tests -v
Ran 104 tests — OK   (was 21 before this batch; +83)
```

`validation-runs/` was intentionally left untouched — regenerating those fixtures is a
separate manual step after review.

## Open

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
- **Standards move fast.** The evidence basis is dated September 2026 and several entries in it
  changed materially during that year. Re-verify `references/ai-visibility-standards-2026.md`
  before the next submission rather than trusting it indefinitely.
- **Sampled crawl.** 5 pages by default. Findings that depend on absence across the site are
  emitted as `likely-risk` with medium confidence, never as `confirmed`.
- **Agent-supplied modes are not exercised by the deterministic pipeline.** `score_fact()`,
  `assess_collision_risk()` and `evaluate_citation_simulation()` need real third-party search
  results and are reachable only through the standalone skill CLIs. This is intentional: the
  alternative is inventing the inputs, which is the bug F8 removed.

---

## Verified-good (don't "fix" these)

- Report schema compliance: four live reports validated against `report-schema.json` with real
  `jsonschema`. All pass.
- All five documented standalone CLI commands in the README run and exit 0.
- Redirect handling (5 hops) and 4xx/5xx vs. timeout distinction work as documented.
- The "missing XML sitemap" findings are **true positives** — python.org, mozilla.org and
  react.dev all genuinely 404 on `/sitemap.xml` with no `Sitemap:` directive in robots.txt.
- The robots.txt *parser* (longest-match, Allow-wins ties) is correct.