# Case study: the site that passes its on-page checks and is still invisible

This is the most instructive result in our validation set. It maps the exact boundary of what a
deterministic, HTML-only audit can and cannot see. We document it rather than hide it, because
knowing where a tool stops being reliable is part of using it well.

## The result

`bbsrgotlaytent.live` returns **zero results in web search** — an AI assistant asked about it
cannot find or cite it. Yet it receives one of the **cleanest reports in our validation set**:
4 findings, none critical, none high (1 medium, 3 low).

| Site | Findings | Critical | High | In AI search? |
|---|---|---|---|---|
| bbsrgotlaytent.live | 4 | 0 | 0 | **No — zero results** |
| fedkiit.com | 5 | 0 | 2 | Partially |
| faktcheck.fedkiit.com | 7 | 0 | 2 | Partially |

The site with the worst real-world outcome gets the calmest report. That looks like a bug. It
isn't.

Full report: [`validation-runs/bbsrgotlaytent-report.json`](../validation-runs/bbsrgotlaytent-report.json).

## Why the report is correct

The site's on-page hygiene is sound. Across the 4 pages crawled, the deterministic checks that
inspect the HTML a crawler actually receives largely pass. The findings that *do* surface are
genuine but minor: the Organization JSON-LD is present but carries no `sameAs` links to
authoritative external profiles (F-001, medium; F-002, low), one deep page has no breadcrumb
trail, and no page exposes a site-search affordance (F-004). None of these is why the site is
invisible in AI search. Inventing higher-severity findings to "explain" the invisibility would
be a false positive — the failure mode our rubric weights most heavily.

The site's real problem is **entirely off-site**: no independent source anywhere on the web
references it. Its identity exists only on its own domain, which is a single fragile source no
matter how clean that domain is. Assistants weight facts that several unrelated sources agree on;
a brand described only by itself has nothing to corroborate. The missing `sameAs` links (F-001)
name the on-page symptom of this — there is nothing to point outward *to* — but the root cause
lives off the domain entirely.

## The boundary this maps

Here is the precise limit. A deterministic pipeline that reads a site's own HTML can observe:

- **The absence of outbound authority links** and the absence of `sameAs` disambiguation from the
  crawled pages. We do flag this.

It **cannot** observe:

- **The absence of the brand from search results themselves** — because that fact does not live
  in the site's HTML. It lives in the index of a search engine the pipeline never queries.

No amount of additional static checks closes this gap. You cannot detect "the rest of the web has
never heard of you" by reading your own homepage more carefully. The signal is not there to read.

## How CiteSense is designed around it

This is why the marketplace has two execution paths, and why the split is deliberate rather than
incidental:

1. **The deterministic path** (`run_audit.py` CLI) runs every check answerable from the site's own
   HTML. It needs no external tools, invents nothing, and is what produces the validation reports.
   On `bbsrgotlaytent.live` it correctly reports sound on-page hygiene and flags the missing
   external corroboration signals it *can* see.

2. **The agent-supplied path** (`citation-simulator` and `trust-corroboration-graph`, reachable
   through the standalone skill CLIs) is where the blind spot is closed. Given an agent with real
   web-search tools, `citation-simulator` runs the actual search → fetch → answer loop a real
   assistant would, and observes directly that the brand does not surface. That is the only way to
   confirm invisibility, and it requires live search results the deterministic path deliberately
   does not fabricate.

We could have made the deterministic path *guess* at search invisibility — emit a confident "you
are not in search results" finding without ever running a search. We refused to, because a finding
whose evidence describes an observation we never made is fabricated evidence, and a regression
test exists specifically to keep that kind of string out of every report.

## The takeaway

`bbsrgotlaytent.live` is the clearest argument in the project for running the marketplace under an
agent with web-search tools rather than only through the CLI. The CLI gives you an honest,
false-positive-free report of everything observable from the site itself. The agent-supplied mode
extends that to the one thing the site's own HTML can never tell you: whether the rest of the web
knows you exist.

A tool that reported this site as "fine" and stopped there would be incomplete. A tool that
fabricated an invisibility finding to look thorough would be dishonest. CiteSense does neither: it
reports what it can confirm, names the on-page symptoms of what it can't, and points to the
execution mode that closes the gap.
