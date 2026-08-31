# Validation runs

Reports regenerated from the current pipeline:

```bash
python skills/audit-orchestrator/scripts/run_audit.py <url> --output validation-runs/<name>-report.json
```

Sites span structural shapes rather than being tuned against: a language project, a docs site,
a large multi-locale org, a framework site, a standards body, and a commercial SaaS. The handout
provides no example sites and states that studied sites are not used in grading -- these are our
own field-research picks, and no detection logic references any of them.

| Site | Runtime | Pages | Findings | Critical | High | Medium | Low | Disc. | Eng. |
|---|---|---|---|---|---|---|---|---|---|
| https://www.python.org | 2.4s | 5 | 5 | 0 | 1 | 3 | 1 | 4 | 1 |
| https://react.dev | 4.9s | 5 | 6 | 0 | 1 | 3 | 2 | 4 | 2 |
| https://www.mozilla.org | 2.6s | 5 | 8 | 0 | 2 | 4 | 2 | 6 | 2 |
| https://www.djangoproject.com | 3.9s | 5 | 4 | 0 | 1 | 2 | 1 | 3 | 1 |
| https://www.iana.org | 1.9s | 5 | 8 | 0 | 1 | 4 | 3 | 5 | 3 |
| https://stripe.com | 11.9s | 5 | 4 | 0 | 1 | 1 | 2 | 2 | 2 |
