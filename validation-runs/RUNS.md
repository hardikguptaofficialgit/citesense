# Validation runs

Reports regenerated from the current pipeline:

```bash
python skills/audit-orchestrator/scripts/run_audit.py <url> --output validation-runs/<name>-report.json
```

The handout provides no example sites and states that studied sites are not used in grading.
These are our own field-research picks, and no detection logic references any of them.

`Score` is `summary.citability_score` (0-100). `Proact.` is beyond-defect recommendations; a
well-optimised site correctly receives fewer.

## Set A -- large, technically well-built sites

Chosen for structural variety. These exercise precision: the risk on a healthy site is crying wolf.

| Site | Shape | Score | Findings | Crit | High | Med | Low | Proact. |
|---|---|---|---|---|---|---|---|---|
| https://www.python.org | language project | 71 | 5 | 0 | 1 | 3 | 1 | 6 |
| https://react.dev | docs site | 69 | 6 | 0 | 1 | 3 | 2 | 5 |
| https://www.mozilla.org | multi-locale org | 52 | 8 | 0 | 2 | 4 | 2 | 6 |
| https://www.djangoproject.com | framework site | 76 | 4 | 0 | 1 | 2 | 1 | 6 |
| https://www.iana.org | standards body | 62 | 8 | 0 | 1 | 4 | 3 | 6 |
| https://stripe.com | commercial SaaS | 79 | 4 | 0 | 1 | 1 | 2 | 3 |

## Set B -- small, niche sites

Added after Set A proved unrepresentative. Every site in Set A is a well-resourced engineering
project, which is the opposite of the scenario this marketplace exists to diagnose. Set B
exercises **recall**: these are the sites that are actually hard to find in AI assistants.

Three bugs were only ever visible here:

- `fedkiit.com` redirects apex to www. The same-site gate compared against the pre-redirect
  origin and refused every internal link, so the crawl stopped at **one page**. Every Set A site
  was seeded with its final hostname, so none exposed it. Fixed; the crawl now reaches 5 pages
  and surfaces a high-severity render gap that was previously invisible.
- `faktcheck.fedkiit.com` was a client-rendered shell serving 5 words of text. The render-gap
  check required the HTML to exceed 1KB, so a compact shell escaped detection entirely. Fixed,
  and the symptom cascade it produced is now suppressed in favour of the single root cause.
- `kforum.me` went offline between audits and now returns **HTTP 404**. The crawl correctly marks
  it inconclusive and emits no page-level findings -- but the citability score, which subtracts
  penalties from 100, then reported **90/100** for a dead site. The score is now withheld
  entirely when no page could be read, with `summary.citability_score_unavailable` explaining why.
  It is kept in this set precisely because it exercises that path.

| Site | Shape | Score | Findings | Crit | High | Med | Low | Proact. |
|---|---|---|---|---|---|---|---|---|
| https://bbsrgotlaytent.live | small event site, server-rendered | 89 | 4 | 0 | 0 | 1 | 3 | 5 |
| https://fedkiit.com | student org, apex redirects to www | 64 | 5 | 0 | 2 | 2 | 1 | 5 |
| https://faktcheck.fedkiit.com | single-page app | 57 | 7 | 0 | 2 | 3 | 2 | 3 |
| https://kforum.me | **offline since 2026-09-07 (HTTP 404)** | withheld | 2 | 0 | 0 | 2 | 0 | 0 |

### Known blind spot, visible in this set

`bbsrgotlaytent.live` returns zero results in web search, yet scores highest of any live site
here. That is not a bug in the checks: its on-site hygiene genuinely is good (Organization
schema, a 7-URL sitemap, headings on every page). Its problem is entirely off-site -- no
independent source anywhere references it -- and the deterministic pipeline can observe the
absence of authority links but cannot observe absence from search itself.

The `corroboration` finding names the right root cause. Confirming it requires the agent-supplied
mode of `citation-simulator`, which needs live search results. This is the clearest argument for
running the marketplace under an agent with web-search tools rather than only via the CLI.
