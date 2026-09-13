# 1,356-Second Benchmark Outlier Investigation

## Result

- Outlier: `ovh.net`
- Original audit start: `2026-09-13T16:16:57.526517+00:00`
- Original audit end: `2026-09-13T16:39:33.551901+00:00`
- Original runtime: `1356.025` seconds
- Final origin: `https://proof.ovh.net`
- Pages sampled: 2
- Readable pages: 2
- Resources observed: 0

The initial crawl took only `21.72` seconds. The delay occurred later in the
engagement broken-link sampler. The sampled `/files/` page exposed 1 MiB, 10
MiB, 100 MiB, 1 GiB, and 10 GiB internal download links.

## Root cause

`safe_fetch()` enforced the 5 MiB response limit only after
`response.read(5 MiB + 1)` returned. A continuously streaming large response
could therefore keep the read active for many minutes while remaining below the
byte limit. The per-read socket timeout did not impose a total response-read
deadline.

DNS resolution also used `socket.getaddrinfo()` without an explicit deadline.
That was hardened in the same shared boundary because a stalled resolver could
produce the same class of unbounded wait.

## Fix

The shared fetch boundary now:

- reads response bodies in bounded chunks;
- stops a continuously streaming response at the existing request timeout;
- preserves the existing raw and decompressed 5 MiB limits;
- bounds hostname resolution with a daemon resolver thread and the same timeout;
- preserves redirect validation and the existing return/access-limited contract.

No detection, scoring, evidence, finding-ID, or marketplace logic changed.

## Reproduction after fix

The exact `https://ovh.net/` audit was rerun using the production entrypoint:

- New runtime: `23.612` seconds
- Pages sampled: 2
- Readable pages: 2
- Crashes: 0
- Timeout failures: 0

The traced rerun measured the five large-file probes at approximately 1–3
seconds each; oversized streaming responses returned the existing
`response-too-large` access result instead of hanging.

## Deterministic regression coverage

Added tests cover:

- continuously streaming responses bounded by the total timeout;
- DNS resolution timeout rejection;
- existing raw/decompressed response limits;
- redirect and SSRF rejection behavior.

The full test suite passes after the fix.
