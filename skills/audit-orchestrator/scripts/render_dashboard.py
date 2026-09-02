#!/usr/bin/env python3
"""
render_dashboard.py -- Renders a report.json into a single self-contained HTML dashboard.

No frameworks, no build step, no external requests: CSS and JS are inlined, so the output
opens straight off the filesystem. Everything rendered comes from the report -- absent
optional sections (proactive_recommendations, citability_score, fix_snippet) are skipped
rather than filled in.

Usage:
    python render_dashboard.py report.json --output dashboard.html
"""
import argparse
import html
import json
import os
import sys
from typing import Any, Dict, List

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from scored import compute_citability_score
from report_io import ReportIOError, fail, load_report, write_text

SEVERITY_ORDER = ("critical", "high", "medium", "low")
SEVERITY_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

# Evidence longer than this is collapsed behind a <details> disclosure.
EVIDENCE_COLLAPSE_CHARS = 220

CSS = """
:root{
  --bg:#0f1117; --panel:#171a23; --panel-2:#1e2230; --line:#2a2f3e;
  --text:#e7e9ee; --muted:#9aa3b5; --accent:#7aa2ff;
  --critical:#ff5c68; --high:#ff9042; --medium:#ffd166; --low:#7bc6a4;
  --disc:#7aa2ff; --eng:#c792ea;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:32px 20px 64px}
header.site{border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:24px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:18px;margin:36px 0 12px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin:0}
.sub a{color:var(--accent);text-decoration:none}
.row{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px;align-items:stretch}
.badge{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;min-width:96px}
.badge .n{font-size:22px;font-weight:600;line-height:1.1}
.badge .l{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.badge.critical .n{color:var(--critical)} .badge.high .n{color:var(--high)}
.badge.medium .n{color:var(--medium)} .badge.low .n{color:var(--low)}
.score{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:10px 18px;display:flex;flex-direction:column;justify-content:center}
.score .n{font-size:26px;font-weight:700}
.score .l{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.score .d{font-size:11px;color:var(--muted);margin-top:2px}
.split{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.bar{display:flex;align-items:center;gap:12px;margin:10px 0}
.bar .k{width:150px;font-size:13px;color:var(--muted);flex-shrink:0}
.bar .track{flex:1;height:14px;background:var(--panel-2);border-radius:7px;overflow:hidden}
.bar .fill{height:100%;border-radius:7px}
.bar .fill.disc{background:var(--disc)} .bar .fill.eng{background:var(--eng)}
.bar .v{width:34px;text-align:right;font-variant-numeric:tabular-nums;font-size:13px}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.filters button{background:var(--panel);color:var(--muted);border:1px solid var(--line);
  border-radius:999px;padding:5px 13px;font-size:12px;cursor:pointer;font-family:inherit}
.filters button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#0f1117;font-weight:600}
.sev-group{margin-top:24px}
.sev-head{display:flex;align-items:center;gap:9px;font-size:13px;font-weight:600;
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.dot.critical{background:var(--critical)} .dot.high{background:var(--high)}
.dot.medium{background:var(--medium)} .dot.low{background:var(--low)}
.card{background:var(--panel);border:1px solid var(--line);border-left-width:3px;
  border-radius:10px;padding:16px 18px;margin-bottom:12px}
.card.critical{border-left-color:var(--critical)} .card.high{border-left-color:var(--high)}
.card.medium{border-left-color:var(--medium)} .card.low{border-left-color:var(--low)}
.card h3{margin:0 0 8px;font-size:15px;font-weight:600;line-height:1.4}
.card h3 .fid{color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums;margin-right:7px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.tag{font-size:11px;border:1px solid var(--line);background:var(--panel-2);color:var(--muted);
  border-radius:5px;padding:2px 8px}
.field{margin-top:10px;font-size:13.5px}
.field .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  display:block;margin-bottom:3px}
.evidence{white-space:pre-wrap;word-break:break-word;color:#c9cedb}
details.ev{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
details.ev>summary{cursor:pointer;font-size:11px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--muted);list-style:none}
details.ev>summary::-webkit-details-marker{display:none}
details.ev>summary::before{content:"\\25B8 ";display:inline-block;transition:transform .15s}
details.ev[open]>summary::before{content:"\\25BE "}
pre.snippet{background:#0b0d13;border:1px solid var(--line);border-radius:8px;padding:12px;
  overflow-x:auto;font-size:12px;line-height:1.45;margin:6px 0 0;
  font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace}
.proactive{background:linear-gradient(180deg,#141d1a,#131a22);border:1px dashed #2f6f57;
  border-radius:10px;padding:16px 18px;margin-bottom:12px}
.proactive h3{margin:0 0 8px;font-size:15px;font-weight:600;color:#8fdcb4}
.proactive .lbl{color:#6f9c88}
.note{color:var(--muted);font-size:13px;font-style:italic}
footer{margin-top:44px;border-top:1px solid var(--line);padding-top:14px;
  color:var(--muted);font-size:12px}
@media (max-width:620px){.bar .k{width:100px}.wrap{padding:20px 14px 48px}}
"""

JS = """
(function(){
  var buttons=document.querySelectorAll('.filters button');
  function apply(sev){
    document.querySelectorAll('.sev-group').forEach(function(g){
      g.style.display=(sev==='all'||g.dataset.severity===sev)?'':'none';
    });
    buttons.forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.filter===sev));});
  }
  buttons.forEach(function(b){b.addEventListener('click',function(){apply(b.dataset.filter);});});
})();
"""


def e(value: Any) -> str:
    """HTML-escapes any value for safe text/attribute interpolation."""
    return html.escape("" if value is None else str(value), quote=True)


def _severity_badges(summary: Dict[str, Any]) -> str:
    parts = []
    for sev in SEVERITY_ORDER:
        count = summary.get(sev, 0)
        parts.append(
            '<div class="badge {s}"><div class="n">{n}</div>'
            '<div class="l">{l}</div></div>'.format(
                s=sev, n=e(count), l=e(SEVERITY_LABEL[sev])
            )
        )
    parts.append(
        '<div class="badge"><div class="n">{n}</div>'
        '<div class="l">Total</div></div>'.format(n=e(summary.get("total_findings", 0)))
    )
    return "".join(parts)


def _score_block(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    if "citability_score" not in summary:
        return ""
    breakdown = compute_citability_score(report)
    detail = "100 base &minus; {p} severity penalty".format(p=e(breakdown["penalty"]))
    if breakdown["corroboration_credit"]:
        detail += " + {c} corroboration credit".format(c=e(breakdown["corroboration_credit"]))
    return (
        '<div class="score"><div class="l">AI-Citability Score</div>'
        '<div class="n">{n}<span style="font-size:14px;color:var(--muted)">/100</span></div>'
        '<div class="d">{d}</div></div>'.format(n=e(summary["citability_score"]), d=detail)
    )


def _split_chart(summary: Dict[str, Any]) -> str:
    disc = summary.get("discoverability_findings", 0) or 0
    eng = summary.get("engagement_findings", 0) or 0
    peak = max(disc, eng, 1)
    rows = []
    for label, value, cls in (
        ("Discoverability", disc, "disc"),
        ("On-site engagement", eng, "eng"),
    ):
        pct = round(value * 100.0 / peak, 1)
        rows.append(
            '<div class="bar"><div class="k">{k}</div>'
            '<div class="track"><div class="fill {c}" style="width:{w}%"></div></div>'
            '<div class="v">{v}</div></div>'.format(k=e(label), c=cls, w=pct, v=e(value))
        )
    uncategorized = (summary.get("total_findings", 0) or 0) - disc - eng
    if uncategorized > 0:
        rows.append(
            '<p class="note">{n} finding(s) carry no discoverability/engagement '
            "category.</p>".format(n=e(uncategorized))
        )
    return '<div class="split">' + "".join(rows) + "</div>"


def _finding_card(finding: Dict[str, Any]) -> str:
    severity = finding.get("severity", "low")
    action = finding.get("suggested_action") or {}
    parts = ['<article class="card {s}">'.format(s=e(severity))]

    fid = finding.get("id")
    heading = ('<span class="fid">{i}</span>'.format(i=e(fid)) if fid else "") + e(
        finding.get("title", "(untitled finding)")
    )
    parts.append("<h3>{h}</h3>".format(h=heading))

    tags = []
    for label, key in (
        ("category", "category"),
        ("status", "status"),
        ("confidence", "confidence"),
        ("impact", "impact"),
    ):
        if finding.get(key):
            tags.append(
                '<span class="tag">{l}: {v}</span>'.format(l=e(label), v=e(finding[key]))
            )
    skills = finding.get("source_skills") or (
        [finding["source_skill"]] if finding.get("source_skill") else []
    )
    if skills:
        tags.append('<span class="tag">source: {v}</span>'.format(v=e(", ".join(skills))))
    if tags:
        parts.append('<div class="meta">' + "".join(tags) + "</div>")

    evidence = str(finding.get("evidence", "")).strip()
    if evidence:
        body = '<div class="evidence">{t}</div>'.format(t=e(evidence))
        if len(evidence) > EVIDENCE_COLLAPSE_CHARS:
            parts.append(
                '<details class="ev"><summary>Evidence ({n} chars)</summary>'
                '<div class="field">{b}</div></details>'.format(n=len(evidence), b=body)
            )
        else:
            parts.append(
                '<div class="field"><span class="lbl">Evidence</span>{b}</div>'.format(b=body)
            )

    if action.get("how_to_fix"):
        parts.append(
            '<div class="field"><span class="lbl">How to fix</span>{t}</div>'.format(
                t=e(action["how_to_fix"])
            )
        )

    if action.get("fix_snippet"):
        parts.append(
            '<details class="ev"><summary>Ready-to-paste JSON-LD snippet</summary>'
            '<pre class="snippet">{s}</pre></details>'.format(s=e(action["fix_snippet"]))
        )

    parts.append("</article>")
    return "".join(parts)


def _findings_section(findings: List[Dict[str, Any]]) -> str:
    if not findings:
        return '<p class="note">No findings recorded in this report.</p>'

    buttons = ['<button data-filter="all" aria-pressed="true">All</button>']
    groups = []
    for sev in SEVERITY_ORDER:
        bucket = [f for f in findings if f.get("severity") == sev]
        if not bucket:
            continue
        buttons.append(
            '<button data-filter="{s}" aria-pressed="false">{l} ({n})</button>'.format(
                s=e(sev), l=e(SEVERITY_LABEL[sev]), n=len(bucket)
            )
        )
        cards = "".join(_finding_card(f) for f in bucket)
        groups.append(
            '<section class="sev-group" data-severity="{s}">'
            '<div class="sev-head"><span class="dot {s}"></span>{l} &middot; {n}</div>'
            "{c}</section>".format(s=e(sev), l=e(SEVERITY_LABEL[sev]), n=len(bucket), c=cards)
        )

    unknown = [f for f in findings if f.get("severity") not in SEVERITY_ORDER]
    if unknown:
        cards = "".join(_finding_card(f) for f in unknown)
        groups.append(
            '<section class="sev-group" data-severity="other">'
            '<div class="sev-head"><span class="dot"></span>Unclassified severity &middot; {n}'
            "</div>{c}</section>".format(n=len(unknown), c=cards)
        )

    return '<div class="filters">' + "".join(buttons) + "</div>" + "".join(groups)


def _proactive_section(recommendations: List[Dict[str, Any]]) -> str:
    cards = []
    for rec in recommendations:
        action = rec.get("suggested_action") or {}
        block = ['<article class="proactive">']
        block.append("<h3>{t}</h3>".format(t=e(rec.get("title", "(untitled recommendation)"))))
        if action.get("priority"):
            block.append(
                '<div class="meta"><span class="tag">priority: {p}</span></div>'.format(
                    p=e(action["priority"])
                )
            )
        if rec.get("rationale"):
            block.append(
                '<div class="field"><span class="lbl proactive-lbl">Rationale</span>{t}</div>'.format(
                    t=e(rec["rationale"])
                )
            )
        if action.get("how_to_fix"):
            block.append(
                '<div class="field"><span class="lbl proactive-lbl">How to implement</span>{t}</div>'.format(
                    t=e(action["how_to_fix"])
                )
            )
        block.append("</article>")
        cards.append("".join(block))
    return (
        "<h2>Proactive Recommendations</h2>"
        '<p class="note">Beyond-defect improvements. These are opportunities, not detected '
        "problems, and they carry no severity and do not affect the citability score.</p>"
        + "".join(cards)
    )


def render_dashboard(report: Dict[str, Any]) -> str:
    """Renders a full report dict into one self-contained HTML document."""
    summary = report.get("summary") or {}
    findings = report.get("findings") or []
    site = str(report.get("site", "(unknown site)"))

    site_link = (
        '<a href="{u}" rel="noreferrer noopener">{u}</a>'.format(u=e(site))
        if site.startswith(("http://", "https://"))
        else e(site)
    )

    body = [
        '<div class="wrap">',
        '<header class="site">',
        "<h1>AI-Readiness Audit</h1>",
        '<p class="sub">{s} &middot; audited at {t}</p>'.format(
            s=site_link, t=e(report.get("audited_at", "unknown time"))
        ),
        '<div class="row">',
        _severity_badges(summary),
        _score_block(report),
        "</div>",
        "</header>",
        "<h2>Discoverability vs. engagement</h2>",
        _split_chart(summary),
        "<h2>Findings</h2>",
        _findings_section(findings),
    ]

    proactive = report.get("proactive_recommendations")
    # Optional per the schema -- skip the whole section when it is absent or empty.
    if isinstance(proactive, list) and proactive:
        body.append(_proactive_section(proactive))

    body.append(
        "<footer>Generated by brand-ai-readiness-audit &middot; render_dashboard.py &middot; "
        "every value shown is read from report.json.</footer>"
    )
    body.append("</div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>AI-Readiness Audit &mdash; {title}</title>\n"
        "<style>{css}</style>\n</head>\n<body>\n{body}\n<script>{js}</script>\n"
        "</body>\n</html>\n"
    ).format(title=e(site), css=CSS, body="\n".join(body), js=JS)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render an audit report.json into a self-contained HTML dashboard."
    )
    parser.add_argument("report", help="Path to a report.json file")
    parser.add_argument(
        "--output", "-o", help="Path to write the HTML file (default: stdout)"
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
        document = render_dashboard(report)
        if args.output:
            write_text(args.output, document)
    except ReportIOError as exc:
        return fail(exc)

    if args.output:
        print(
            json.dumps(
                {
                    "status": "written",
                    "output": args.output,
                    "site": report.get("site"),
                    "findings_rendered": len(report.get("findings") or []),
                    "proactive_rendered": len(report.get("proactive_recommendations") or []),
                },
                indent=2,
            )
        )
    else:
        sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
