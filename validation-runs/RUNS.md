# Validation runs

Reports regenerated from the current pipeline. Each was produced with:

```bash
python skills/audit-orchestrator/scripts/run_audit.py <url> --output validation-runs/<name>-report.json
```

Sites were chosen to span structural shapes, not to tune against: a docs site (react.dev),
a large multi-locale org (mozilla.org), a language project (python.org), a framework site
(djangoproject.com), a standards body (iana.org), and a commercial SaaS (stripe.com).

| Site | Runtime | Findings | Critical | High | Medium | Low |
|---|---|---|---|---|---|---|
| https://www.python.org | 1.7s | 5 | 0 | 1 | 3 | 1 |
| https://react.dev | 4.3s | 5 | 0 | 1 | 3 | 1 |
| https://www.mozilla.org | 2.0s | 7 | 0 | 2 | 4 | 1 |
| https://www.djangoproject.com | 3.1s | 4 | 0 | 1 | 2 | 1 |
| https://www.iana.org | 4.8s | 6 | 0 | 1 | 4 | 1 |
| https://stripe.com | 16.3s | 4 | 0 | 1 | 1 | 2 |
