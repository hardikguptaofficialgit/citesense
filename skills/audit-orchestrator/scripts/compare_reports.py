#!/usr/bin/env python3
"""
compare_reports.py -- Diffs two audit reports for the same site (before/after a fix, or
two points in time) and reports what was resolved, what is new, and what persists.

Findings are matched by their stable `fingerprint`. When either side lacks a fingerprint
the pair falls back to (category, normalized title) -- the same fallback key
compose_report.dedupe uses, so matching stays consistent with how findings are merged.

Usage:
    python compare_reports.py before.json after.json --output diff.json
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from compose_report import normalize_title
from report_io import ReportIOError, fail, load_report, write_text

# Net-improvement weights for score_delta. Deliberately a flat 4/3/2/1 severity ladder --
# this measures *how many findings of what rank* went away, and is intentionally distinct
# from the citability score's steeper penalties (see references/citability-score.md).
SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def match_key(finding: Dict[str, Any]) -> Tuple[str, str]:
    """
    Stable identity for cross-report matching.
    Returns ("fingerprint", <value>) when available, else ("title", "<category>|<norm title>").
    """
    fingerprint = finding.get("fingerprint")
    if fingerprint:
        return ("fingerprint", str(fingerprint))
    return (
        "title",
        "{0}|{1}".format(
            finding.get("category") or "", normalize_title(finding.get("title") or "")
        ),
    )


def _fallback_key(finding: Dict[str, Any]) -> Tuple[str, str]:
    """The title-based key, computed even for findings that do have a fingerprint."""
    return (
        "title",
        "{0}|{1}".format(
            finding.get("category") or "", normalize_title(finding.get("title") or "")
        ),
    )


def _index(findings: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Indexes findings by primary key, keeping the first occurrence on collision."""
    index = {}
    for f in findings:
        key = match_key(f)
        index.setdefault(key, f)
    return index


def weighted_total(findings: List[Dict[str, Any]]) -> int:
    """Sum of severity weights across a findings list."""
    return sum(SEVERITY_WEIGHT.get(f.get("severity"), 0) for f in findings)


def _same_site(before_site: Any, after_site: Any) -> bool:
    """True when both reports name the same origin (ignoring trailing-slash drift)."""
    if not before_site or not after_site:
        return True  # Nothing to contradict; do not warn on incomplete metadata.
    return str(before_site).rstrip("/") == str(after_site).rstrip("/")


def _brief(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Compact record of a finding for the diff output."""
    out = {
        "id": finding.get("id"),
        "title": finding.get("title"),
        "category": finding.get("category"),
        "severity": finding.get("severity"),
        "fingerprint": finding.get("fingerprint"),
    }
    return {k: v for k, v in out.items() if v is not None}


def compare_reports(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns the diff object:
        {"before": {...}, "after": {...}, "resolved": [...], "new": [...],
         "unchanged": [...], "score_delta": int, "citability_score_delta": int|None,
         "summary": {...}}
    score_delta is sum(weights in before) - sum(weights in after): positive means the
    site improved (findings went away or got less severe).
    """
    before_findings = before.get("findings") or []
    after_findings = after.get("findings") or []

    before_index = _index(before_findings)
    after_index = _index(after_findings)

    # Secondary lookup so a finding that gained or lost its fingerprint between runs still
    # matches its counterpart by (category, normalized title).
    after_by_title: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in after_findings:
        after_by_title.setdefault(_fallback_key(f), f)
    before_by_title: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in before_findings:
        before_by_title.setdefault(_fallback_key(f), f)

    matched_after_ids = set()
    resolved: List[Dict[str, Any]] = []
    unchanged: List[Dict[str, Any]] = []

    for key, b in before_index.items():
        a = after_index.get(key)
        if a is None:
            a = after_by_title.get(_fallback_key(b))
        if a is None:
            resolved.append(_brief(b))
            continue

        matched_after_ids.add(id(a))
        entry = _brief(a)
        entry["previous_id"] = b.get("id")
        entry["previous_severity"] = b.get("severity")
        b_sev, a_sev = b.get("severity"), a.get("severity")
        entry["severity_changed"] = b_sev != a_sev
        if b_sev != a_sev:
            b_rank = SEVERITY_RANK.get(b_sev, 4)
            a_rank = SEVERITY_RANK.get(a_sev, 4)
            entry["severity_change"] = (
                "worsened" if a_rank < b_rank else "improved" if a_rank > b_rank else "changed"
            )
        unchanged.append(entry)

    new: List[Dict[str, Any]] = []
    for key, a in after_index.items():
        if id(a) in matched_after_ids:
            continue
        if key in before_index or _fallback_key(a) in before_by_title:
            continue
        new.append(_brief(a))

    before_total = weighted_total(before_findings)
    after_total = weighted_total(after_findings)

    before_score = (before.get("summary") or {}).get("citability_score")
    after_score = (after.get("summary") or {}).get("citability_score")
    citability_delta = (
        after_score - before_score
        if isinstance(before_score, int) and isinstance(after_score, int)
        else None
    )

    return {
        "before": {
            "site": before.get("site"),
            "audited_at": before.get("audited_at"),
            "total_findings": len(before_findings),
            "weighted_severity_total": before_total,
        },
        "after": {
            "site": after.get("site"),
            "audited_at": after.get("audited_at"),
            "total_findings": len(after_findings),
            "weighted_severity_total": after_total,
        },
        "same_site": _same_site(before.get("site"), after.get("site")),
        "resolved": resolved,
        "new": new,
        "unchanged": unchanged,
        "score_delta": before_total - after_total,
        "citability_score_delta": citability_delta,
        "summary": {
            "resolved_count": len(resolved),
            "new_count": len(new),
            "unchanged_count": len(unchanged),
            "severity_changed_count": sum(1 for u in unchanged if u.get("severity_changed")),
            "no_changes": not resolved
            and not new
            and not any(u.get("severity_changed") for u in unchanged),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff two audit reports and summarize net improvement."
    )
    parser.add_argument("before", help="Path to the earlier report.json")
    parser.add_argument("after", help="Path to the later report.json")
    parser.add_argument("--output", "-o", help="Path to write the diff JSON (default: stdout)")
    args = parser.parse_args(argv)

    try:
        before = load_report(args.before, label="before report")
        after = load_report(args.after, label="after report")
        diff = compare_reports(before, after)
        text = json.dumps(diff, indent=2)
        if args.output:
            write_text(args.output, text)
    except ReportIOError as exc:
        return fail(exc)

    if not diff["same_site"]:
        sys.stderr.write(
            "warning: comparing two different sites ({0} vs {1}); "
            "resolved/new buckets reflect the site change, not a fix.\n".format(
                diff["before"]["site"], diff["after"]["site"]
            )
        )

    if args.output:
        print(
            json.dumps(
                {
                    "status": "written",
                    "output": args.output,
                    "score_delta": diff["score_delta"],
                    "summary": diff["summary"],
                },
                indent=2,
            )
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
