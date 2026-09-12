#!/usr/bin/env python3
"""
priority_order.py -- Ranks the final findings into a short "do these first" list.

Answers the question a report's severity grouping does not: of everything found, which fixes
return the most for the least work? Like scored.py it is a pure, deterministic function of the
*final* findings list, so the order can be recomputed by hand from report.json.

Inputs are only fields findings already carry -- impact (falling back to severity, as the schema
permits), severity, category -- plus the optional effort rung. Effort not declared on a finding
is resolved from its category via models.CATEGORY_DEFAULT_EFFORT, the single source of truth.
An unrecognised category gets no guessed effort: it is reported as null and ranked after every
classified effort at the same impact.

Ordering (ascending sort key, every component explicit so dict order never matters):
    1. impact    critical < high < medium < low < unknown
    2. effort    trivial < moderate < involved < unknown
    3. severity  critical < high < medium < low < unknown
    4. id        lexicographic ("F-001" < "F-002")
    5. title     lexicographic -- only reachable when ids are missing or duplicated
Impact dominates, so a high-impact involved fix still outranks a medium-impact trivial one;
effort only reorders fixes of equal impact, floating the cheap wins to the top of each tier.
"""
import os
import sys
from typing import Any, Dict, List, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from models import EFFORT_LEVELS, resolve_effort

MAX_PRIORITY_FIXES = 5

LEVEL_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
EFFORT_RANK = {effort: i for i, effort in enumerate(EFFORT_LEVELS)}
UNKNOWN_RANK = 99


def _impact(finding: Dict[str, Any]) -> Optional[str]:
    """Impact when valid, else severity -- report-schema.json says consumers may treat them equal."""
    impact = finding.get("impact")
    return impact if impact in LEVEL_RANK else finding.get("severity")


def _sort_key(finding: Dict[str, Any]):
    effort = resolve_effort(finding.get("category"), finding.get("effort"))
    return (
        LEVEL_RANK.get(_impact(finding), UNKNOWN_RANK),
        EFFORT_RANK.get(effort, UNKNOWN_RANK),
        LEVEL_RANK.get(finding.get("severity"), UNKNOWN_RANK),
        str(finding.get("id") or ""),
        str(finding.get("title") or ""),
    )


def build_rationale(impact: Optional[str], effort: Optional[str]) -> str:
    """One generated sentence explaining the rank. Built only from impact and effort."""
    impact_text = f"{impact.capitalize()} impact" if impact in LEVEL_RANK else "Unclassified impact"
    if effort not in EFFORT_RANK:
        return f"{impact_text}, effort not classified — ranked by impact alone."
    heavy = impact in ("critical", "high")
    if effort == "trivial":
        tail = "best return for effort." if heavy else "a quick win once higher-impact fixes are done."
    elif effort == "moderate":
        tail = "worth scheduling now." if heavy else "ranked below higher-impact and easier fixes."
    else:
        tail = "the stakes justify the larger effort." if heavy else "ranked below higher-impact and easier fixes."
    return f"{impact_text}, {effort} fix — {tail}"


def rank_priority_fixes(
    findings: List[Dict[str, Any]], limit: int = MAX_PRIORITY_FIXES
) -> List[Dict[str, Any]]:
    """
    Returns up to `limit` entries, best first:
        {"id", "title", "severity", "impact", "effort", "rationale"}
    Empty input yields an empty list. The input list is not modified.
    """
    ranked = sorted((f for f in findings or [] if isinstance(f, dict)), key=_sort_key)
    out = []
    for f in ranked[:limit]:
        impact = _impact(f)
        effort = resolve_effort(f.get("category"), f.get("effort"))
        out.append({
            "id": f.get("id"),
            "title": f.get("title"),
            "severity": f.get("severity"),
            "impact": impact,
            "effort": effort,
            "rationale": build_rationale(impact, effort),
        })
    return out


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    from report_io import ReportIOError, fail, load_report

    parser = argparse.ArgumentParser(
        description="Recompute the priority fix order (impact vs. effort) for an audit report."
    )
    parser.add_argument("report", help="Path to a report.json file")
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
    except ReportIOError as exc:
        return fail(exc)

    print(json.dumps({"priority_fix_order": rank_priority_fixes(report.get("findings") or [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
