# Progress

Change log for `brand-ai-readiness-audit` (Adobe University Hackathon 2026, Round 3).
Each entry records **root cause → change → how verified**.

Constraints every entry is held to: Python standard library only (no new dependencies, no
model weights, small zip); no fabricated data — every value shown to a user must come from
`report.json` or the `SiteInventory`; `references/report-schema.json` is a floor, so fields
may be added but never removed and never made optional-if-previously-required.

> **Note on this file:** `Progress.md` did not exist in the repository before this batch
> (`git log --all -- Progress.md` is empty), so it starts at F-008. F-001 – F-007 in the
> table below reconstruct the features already shipped in commits `3003fed` and `74cb328`
> from the code and README as they stand, and are marked as such.

---

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
