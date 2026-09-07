#!/usr/bin/env python3
"""
scored.py -- Computes the AI-Citability Score (0-100) for a composed audit report.

The score is a deliberately simple, fully deterministic function of the *final* findings
list, so a judge can recompute it by hand from report.json. The formula and its rationale
are documented in references/citability-score.md; this module is the executable copy of it.

Design rules:
  - Deterministic: identical findings always produce an identical score.
  - Monotonic: adding a finding never raises the score.
  - No fabricated inputs: credit is only awarded from signals actually present in the
    report. A report that carries no corroboration signal receives 0 credit, not a guess.
"""
from typing import Any, Dict, List, Optional

# Severity penalties. Ratios mirror the escalation in crawl-render-audit's severity-guide:
# a critical finding (the site is silently invisible to the assistants that matter) is
# roughly twice as damaging as a high, and a high roughly twice a medium.
SEVERITY_PENALTY = {"critical": 25, "high": 12, "medium": 5, "low": 2}

# Corroboration credit: awarded per distinct fact the trust-corroboration-graph actually
# scored as independently "strong". Absent that signal the credit is 0 -- never assumed.
STRONG_CORROBORATION_CREDIT = 2
MAX_CORROBORATION_CREDIT = 6

SCORE_FLOOR = 0
SCORE_CEILING = 100


def _corroboration_signals(report: Dict[str, Any]) -> List[str]:
    """
    Collects corroboration_strength values that are genuinely recorded in the report.

    Looked for in two places, both additive/optional:
      - report['summary']['corroboration_strengths'] (list of strings), and
      - findings[].evidence_details['corroboration_strength'].
    Nothing is inferred when neither is present.
    """
    signals: List[str] = []
    summary = report.get("summary")
    if isinstance(summary, dict):
        recorded = summary.get("corroboration_strengths")
        if isinstance(recorded, list):
            signals.extend(str(s) for s in recorded)
    for f in report.get("findings", []) or []:
        details = f.get("evidence_details")
        if isinstance(details, dict) and details.get("corroboration_strength"):
            signals.append(str(details["corroboration_strength"]))
    return signals


def compute_citability_score(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns the score plus the full arithmetic behind it, so the number is auditable:
        {"score": int, "base": 100, "penalty": int, "penalty_by_severity": {...},
         "corroboration_credit": int, "counted_findings": int}
    """
    penalty_by_severity = {sev: 0 for sev in SEVERITY_PENALTY}
    counted = 0
    penalty = 0

    for f in report.get("findings", []) or []:
        severity = f.get("severity")
        weight = SEVERITY_PENALTY.get(severity)
        if weight is None:
            # Unknown severity contributes nothing rather than a guessed weight.
            continue
        penalty_by_severity[severity] += weight
        penalty += weight
        counted += 1

    strong = sum(1 for s in _corroboration_signals(report) if s == "strong")
    credit = min(strong * STRONG_CORROBORATION_CREDIT, MAX_CORROBORATION_CREDIT)

    raw = SCORE_CEILING - penalty + credit
    score = max(SCORE_FLOOR, min(SCORE_CEILING, raw))

    return {
        "score": score,
        "base": SCORE_CEILING,
        "penalty": penalty,
        "penalty_by_severity": penalty_by_severity,
        "corroboration_credit": credit,
        "counted_findings": counted,
    }


def citability_score(report: Dict[str, Any]) -> int:
    """Convenience wrapper returning just the 0-100 integer."""
    return compute_citability_score(report)["score"]


def annotate_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Writes summary['citability_score'] in place and returns the report."""
    summary = report.get("summary")
    if isinstance(summary, dict):
        summary["citability_score"] = citability_score(report)
    return report


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from report_io import ReportIOError, fail, load_report

    parser = argparse.ArgumentParser(
        description="Compute the AI-Citability Score for an audit report."
    )
    parser.add_argument("report", help="Path to a report.json file")
    parser.add_argument(
        "--explain", action="store_true", help="Print the full score breakdown"
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
    except ReportIOError as exc:
        return fail(exc)

    breakdown = compute_citability_score(report)
    print(json.dumps(breakdown if args.explain else {"citability_score": breakdown["score"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
