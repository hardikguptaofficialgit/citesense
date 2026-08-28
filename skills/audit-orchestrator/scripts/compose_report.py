#!/usr/bin/env python3
"""
compose_report.py -- merges per-skill finding lists into the final audit report.

Two modes:
  merge:    combine N JSON files (each a JSON array of finding objects produced by a
            data-gathering skill) into the single final report matching report-schema.json.
            Assigns sequential ids (F-001, F-002, ...), deduplicates near-identical findings
            (same category + near-identical title), and computes the summary block.
  validate: check an assembled report against the required-field shape (structural check,
            not a full JSON-Schema validator, but catches missing required fields / bad enums).

Usage:
    python3 compose_report.py merge --site https://example.com \
        --input crawl_findings.json freshness_findings.json engagement_findings.json \
                trust_findings.json citation_findings.json \
        [--proactive proactive_recommendations.json] \
        [--output report.json]

    python3 compose_report.py validate --input report.json
"""
import sys
import json
import argparse
import re
from datetime import datetime, timezone

DISCOVERABILITY_CATEGORIES = {
    "crawlability", "render-gap", "structured-data", "fact-extractability",
    "freshness", "internal-consistency", "corroboration", "entity-disambiguation",
    "citation-omission", "citation-misattribution", "citation-staleness", "citation-contradiction",
}
ENGAGEMENT_CATEGORIES = {"orientation", "navigation", "personalization-readiness"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
REQUIRED_FINDING_FIELDS = {"id", "title", "severity", "evidence", "suggested_action"}


def normalize_title(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def load_findings(paths):
    all_findings = []
    for p in paths:
        # Accept normal UTF-8 and UTF-8 with BOM from PowerShell/Windows tooling.
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{p} must contain a JSON array of finding objects")
        all_findings.extend(data)
    return all_findings


def dedupe(findings):
    """Merge only same-root-cause findings; preserve multiple independent observations."""
    merged = {}
    order = []
    for f in findings:
        # Producers may set a stable fingerprint.  Fallback is deliberately conservative.
        key = f.get("fingerprint") or (f.get("category"), normalize_title(f.get("title", "")))
        if key in merged:
            existing = merged[key]
            extra_evidence = f.get("evidence", "")
            skill = f.get("source_skill", "")
            if extra_evidence and extra_evidence not in existing["evidence"]:
                existing["evidence"] += f"\nAdditional evidence ({skill or 'another check'}): {extra_evidence}"
            sources = set(existing.get("source_skills", [existing.get("source_skill", "")]))
            if skill: sources.add(skill)
            existing["source_skills"] = sorted(s for s in sources if s)
            existing_sev = existing.get("severity")
            new_sev = f.get("severity")
            sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            if sev_rank.get(new_sev, -1) > sev_rank.get(existing_sev, -1):
                existing["severity"] = new_sev
        else:
            merged[key] = dict(f)
            order.append(key)
    return [merged[k] for k in order]


def assign_ids_and_validate(findings):
    out = []
    for i, f in enumerate(findings, start=1):
        f = dict(f)
        f["id"] = f"F-{i:03d}"
        missing = REQUIRED_FINDING_FIELDS - set(f.keys())
        if missing:
            raise ValueError(f"finding '{f.get('title')}' missing required fields: {missing}")
        if f["severity"] not in VALID_SEVERITIES:
            raise ValueError(f"finding '{f['id']}' has invalid severity '{f['severity']}'")
        sa = f.get("suggested_action", {})
        if not isinstance(sa, dict) or not sa.get("summary") or not sa.get("priority") or not sa.get("how_to_fix"):
            raise ValueError(f"finding '{f['id']}' suggested_action requires summary, priority, and how_to_fix")
        if sa["priority"] not in VALID_SEVERITIES: raise ValueError(f"finding '{f['id']}' has invalid action priority")
        if not isinstance(f["evidence"], str) or len(f["evidence"].strip()) < 12: raise ValueError(f"finding '{f['id']}' needs concrete evidence")
        out.append(f)
    return out


def compute_summary(findings):
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    discoverability = 0
    engagement = 0
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        cat = f.get("category")
        if cat in DISCOVERABILITY_CATEGORIES:
            discoverability += 1
        elif cat in ENGAGEMENT_CATEGORIES:
            engagement += 1
    return {
        "total_findings": len(findings),
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "discoverability_findings": discoverability,
        "engagement_findings": engagement,
    }


def merge_mode(args):
    findings = load_findings(args.input)
    findings = dedupe(findings)
    # sort by severity (critical first) before assigning sequential ids, so F-001 is the
    # most urgent item -- makes the report more immediately actionable for a non-expert
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: sev_rank.get(f.get("severity"), 4))
    findings = assign_ids_and_validate(findings)

    report = {
        "site": args.site,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": compute_summary(findings),
        "findings": findings,
    }

    if args.proactive:
        with open(args.proactive, encoding="utf-8-sig") as f:
            proactive = json.load(f)
        if not isinstance(proactive, list):
            raise ValueError("--proactive file must contain a JSON array")
        report["proactive_recommendations"] = proactive

    output_text = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(json.dumps({"status": "written", "output": args.output, "finding_count": len(findings)}, indent=2))
    else:
        print(output_text)


def validate_mode(args):
    with open(args.input[0], encoding="utf-8-sig") as f:
        report = json.load(f)
    errors = []
    for field in ("site", "audited_at", "summary", "findings"):
        if field not in report:
            errors.append(f"missing top-level field: {field}")
    for f in report.get("findings", []):
        missing = REQUIRED_FINDING_FIELDS - set(f.keys())
        if missing:
            errors.append(f"finding {f.get('id', '?')} missing fields: {missing}")
        if f.get("severity") not in VALID_SEVERITIES:
            errors.append(f"finding {f.get('id', '?')} has invalid severity: {f.get('severity')}")
        action=f.get("suggested_action")
        if not isinstance(action,dict) or not all(action.get(x) for x in ("summary","priority","how_to_fix")):
            errors.append(f"finding {f.get('id', '?')} suggested_action requires summary, priority, how_to_fix")
    summary=report.get("summary",{})
    if isinstance(summary,dict):
        for sev in VALID_SEVERITIES:
            if not isinstance(summary.get(sev),int): errors.append(f"summary missing integer {sev} count")
        if summary.get("total_findings") != len(report.get("findings",[])): errors.append("summary total_findings does not match findings")
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        sys.exit(1)
    else:
        print(json.dumps({"valid": True}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    merge_p = sub.add_parser("merge")
    merge_p.add_argument("--site", required=True)
    merge_p.add_argument("--input", nargs="+", required=True)
    merge_p.add_argument("--proactive")
    merge_p.add_argument("--output")

    validate_p = sub.add_parser("validate")
    validate_p.add_argument("--input", nargs=1, required=True)

    args = parser.parse_args()
    if args.mode == "merge":
        merge_mode(args)
    else:
        validate_mode(args)


if __name__ == "__main__":
    main()
