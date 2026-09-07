# AI-Citability Score

A single 0-100 number summarizing how safely an AI assistant can find, read, and quote a
site. It is written to `report["summary"]["citability_score"]` as an **optional additive
field** — the required schema fields are untouched, and any consumer that ignores it still
reads a valid report.

The executable copy of this formula is
[`scripts/scored.py`](../scripts/scored.py). This document is the reference a judge should
be able to hold next to a `report.json` and recompute the number by hand.

---

## The formula

```
penalty  = Σ over findings   SEVERITY_PENALTY[finding.severity]
credit   = min(2 × (# facts recorded as corroboration_strength "strong"), 6)

score    = clamp(0, 100, 100 − penalty + credit)
```

| Severity | Penalty |
|---|---|
| `critical` | 25 |
| `high` | 12 |
| `medium` | 5 |
| `low` | 2 |

A finding whose `severity` is not one of those four contributes **0** rather than a guessed
weight — an unrecognized severity is missing data, not a free pass or an assumed penalty.

### Worked example

The Mozilla report in `report.json` has 1 high, 4 medium, 2 low and no recorded
corroboration signal:

```
penalty = (1 × 12) + (4 × 5) + (2 × 2) = 36
credit  = 0
score   = 100 − 36 + 0 = 64
```

Verify any report with:

```bash
python skills/audit-orchestrator/scripts/scored.py report.json --explain
```

which prints the full arithmetic (`base`, `penalty`, `penalty_by_severity`,
`corroboration_credit`, `counted_findings`), not just the number.

---

## Why these weights

The ratios follow the escalation already documented in
[`crawl-render-audit/references/severity-guide.md`](../../crawl-render-audit/references/severity-guide.md),
where each severity step represents a qualitatively different failure, not a linear one:

- **critical (25)** — the site is *silently invisible*: an AI-assistant user agent is
  disallowed while `*` is open, or the whole site is blocked. Nothing else on the page
  matters if the crawler never arrives. Four of these floor the score at 0, which is the
  intended reading: a site no assistant can reach is not citable at any percentage.
- **high (12)** — content or facts exist but are *not machine-extractable* (render gap, no
  JSON-LD on a money page). Roughly half a critical: the assistant arrives and leaves with
  nothing reliable. Nine of these also floor the score.
- **medium (5)** — the entity resolves but is *incomplete or ambiguous* (partial schema,
  missing canonical, no sitemap). Roughly half a high. A site can carry several of these
  and still be broadly citable, which the score reflects.
- **low (2)** — *friction*, not failure (missing `sameAs`, missing breadcrumbs on a deep
  path). Deliberately small: a report full of nitpicks should not read like a broken site.

The absolute scale is anchored so that a clean audit scores 100 and a realistically flawed
mid-sized site — the Mozilla run above — lands in the 60s rather than the 90s or the teens.
A score in the 90s should mean "almost nothing to fix", not "we found five things".

---

## Why credit is narrow (and why some credit does not exist)

**Corroboration credit is data-gated.** `trust-corroboration-graph` classifies a claim as
`strong` only when **two or more independent, non-brand-owned domains** support it with
evidence (see `corroboration_scorer.score_fact`). That is a genuine positive signal about
the site's external standing that no finding captures, so it earns back up to 6 points,
2 per independently corroborated fact.

The credit is read only from signals actually recorded in the report:

- `report["summary"]["corroboration_strengths"]` — a list of strength strings, or
- `findings[].evidence_details["corroboration_strength"]`.

**A report carrying neither receives 0 credit — never an assumed or estimated value.**
Most reports today carry no such signal, so in practice the score is `100 − penalty`. That
is the honest outcome: the score never invents an input it was not given.

**Proactive recommendation count deliberately earns no credit.** It would be tempting to
award points per `proactive_recommendations` entry, but those entries describe work the
*auditor* suggested, not anything the *site* did. Rewarding them would mean a site's score
rose because we wrote more suggestions about it — the number would measure our output, not
the site's readiness, and it would move in the wrong direction (more advice ⇒ better score).
Proactive recommendations are therefore surfaced prominently in the report and dashboard,
and excluded from the arithmetic entirely.

---

## Guaranteed properties

Both are pinned by `tests/test_citability_score.py`:

1. **Deterministic.** The score is a pure function of the findings list and the recorded
   corroboration signals. The same report always yields the same number — no clock, no
   randomness, no network.
2. **Monotonic.** Every severity carries a strictly positive penalty and credit is
   independent of the findings count, so **adding a finding can never raise the score**.
   At the floor it stays at 0 rather than going negative, which preserves monotonicity
   (non-increasing) at the bottom of the range.

---

## Relationship to `compare_reports.py --output diff.json`

`compare_reports.py` reports a separate `score_delta` on a flat `critical=4 / high=3 /
medium=2 / low=1` ladder. The two numbers answer different questions and are intentionally
not the same scale:

| | Question | Scale |
|---|---|---|
| `citability_score` | How citable is this site *right now*? | 0-100, steep — a critical dominates |
| `score_delta` | How much did the finding load change *between two runs*? | Unbounded, flat — counts findings by rank |

A diff between two reports that both carry `citability_score` additionally reports
`citability_score_delta` (after − before), so an improvement shows as a positive number on
both measures.
