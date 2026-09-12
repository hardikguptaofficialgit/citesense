#!/usr/bin/env python3
"""
compose_report.py -- Merges, deduplicates, prioritizes, and validates audit findings into the final report.
Strictly adheres to report-schema.json while preserving candidate finding metadata (status, confidence, impact).
"""
import sys
import os
import json
import argparse
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Set, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
crawl_scripts_dir = os.path.abspath(os.path.join(current_dir, "../../crawl-render-audit/scripts"))
for d in (current_dir, crawl_scripts_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from fix_snippets import attach_fix_snippets
from scored import annotate_report

# Single source of truth: these sets live in models.py. Redefining them here let the two
# drift silently, which would mis-split the discoverability/engagement summary counts.
from models import DISCOVERABILITY_CATEGORIES, ENGAGEMENT_CATEGORIES, VALID_SEVERITIES
REQUIRED_FINDING_FIELDS = {"id", "title", "severity", "evidence", "suggested_action"}

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def normalize_title(title: str) -> str:
    """Normalizes finding titles for fuzzy deduplication."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def load_findings(paths: List[str]) -> List[Dict[str, Any]]:
    """Loads candidate findings from one or more JSON files."""
    all_findings = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_findings.extend(data)
        elif isinstance(data, dict) and "findings" in data:
            all_findings.extend(data["findings"])
        else:
            raise ValueError(f"{p} must contain a JSON array of finding objects")
    return all_findings


def dedupe(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge findings sharing the same root cause (by fingerprint or category+normalized title).
    Consolidates evidence, tracks all reporting source skills, and keeps highest severity/impact.
    """
    merged = {}
    order = []

    for f in findings:
        key = f.get("fingerprint") or (f.get("category"), normalize_title(f.get("title", "")))
        if key in merged:
            existing = merged[key]
            extra_evidence = f.get("evidence", "")
            skill = f.get("source_skill", "")

            # Merge evidence without duplication
            if extra_evidence and extra_evidence not in existing.get("evidence", ""):
                existing["evidence"] = existing.get("evidence", "") + f"\nAdditional evidence ({skill or 'another check'}): {extra_evidence}"

            # Merge source skills
            sources = set(existing.get("source_skills", [existing.get("source_skill", "")]))
            if skill:
                sources.add(skill)
            existing["source_skills"] = sorted(s for s in sources if s)

            # Elevate severity to highest
            existing_sev = existing.get("severity", "low")
            new_sev = f.get("severity", "low")
            if SEVERITY_RANK.get(new_sev, 4) < SEVERITY_RANK.get(existing_sev, 4):
                existing["severity"] = new_sev
                if existing.get("suggested_action") and f.get("suggested_action"):
                    existing["suggested_action"]["priority"] = new_sev

            # Elevate impact to highest
            existing_imp = existing.get("impact", existing_sev)
            new_imp = f.get("impact", new_sev)
            if SEVERITY_RANK.get(new_imp, 4) < SEVERITY_RANK.get(existing_imp, 4):
                existing["impact"] = new_imp

        else:
            merged[key] = dict(f)
            order.append(key)

    return [merged[k] for k in order]


def assign_ids_and_validate(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assigns sequential F-NNN IDs and enforces required report schema constraints."""
    out = []
    for i, f in enumerate(findings, start=1):
        item = dict(f)
        item["id"] = f"F-{i:03d}"
        missing = REQUIRED_FINDING_FIELDS - set(item.keys())
        if missing:
            raise ValueError(f"finding '{item.get('title')}' missing required fields: {missing}")
        if item["severity"] not in VALID_SEVERITIES:
            raise ValueError(f"finding '{item['id']}' has invalid severity '{item['severity']}'")
        
        sa = item.get("suggested_action", {})
        if not isinstance(sa, dict) or not sa.get("summary") or not sa.get("priority") or not sa.get("how_to_fix"):
            raise ValueError(f"finding '{item['id']}' suggested_action requires summary, priority, and how_to_fix")
        if sa["priority"] not in VALID_SEVERITIES:
            raise ValueError(f"finding '{item['id']}' has invalid action priority")
        if not isinstance(item["evidence"], str) or len(item["evidence"].strip()) < 10:
            raise ValueError(f"finding '{item['id']}' needs concrete evidence")

        out.append(item)
    return out


def compute_summary(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes summary counts by severity and discoverability/engagement split."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    discoverability = 0
    engagement = 0

    for f in findings:
        sev = f.get("severity", "low")
        counts[sev] = counts.get(sev, 0) + 1
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


def build_final_report(
    site_url: str,
    findings: List[Dict[str, Any]],
    proactive_recommendations: Optional[List[Dict[str, Any]]] = None,
    ground_truth: Optional[Dict[str, Any]] = None,
    pages: Optional[Dict[str, Any]] = None,
    access_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assembles, deduplicates, prioritizes, and formats the final report object.

    When `ground_truth` (and optionally the cached `pages` snapshots) are supplied, every
    qualifying structured-data finding also receives a pre-populated JSON-LD
    `suggested_action.fix_snippet`. Snippets are only attached where the observed data is
    rich enough to fill the entity's identifying fields -- see fix_snippets.py.
    """
    deduped = dedupe(findings)
    # Sort by severity (critical first) then impact
    deduped.sort(key=lambda f: (SEVERITY_RANK.get(f.get("severity"), 4), SEVERITY_RANK.get(f.get("impact", f.get("severity")), 4)))
    validated_findings = assign_ids_and_validate(deduped)

    # Auto-generate ready-to-paste JSON-LD fixes from data the crawl actually observed.
    attach_fix_snippets(
        validated_findings,
        ground_truth=ground_truth,
        pages=pages,
        site_url=site_url,
    )

    report = {
        "site": site_url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": compute_summary(validated_findings),
        "findings": validated_findings,
    }

    if access_summary is not None:
        report["access_summary"] = access_summary

    if proactive_recommendations:
        report["proactive_recommendations"] = proactive_recommendations

    # Additive 0-100 AI-Citability Score (see references/citability-score.md).
    annotate_report(report, pages=pages)

    return report


def load_context(path: Optional[str]) -> Dict[str, Any]:
    """
    Loads fix-snippet context from a saved SiteInventory JSON (as written by
    run_audit.py --save-inventory) or from a bare ground_truth JSON object.
    Returns {"ground_truth": {...}, "pages": {...}}.
    """
    if not path or not os.path.exists(path):
        return {"ground_truth": None, "pages": None}
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("--inventory file must contain a JSON object")
    if "ground_truth" in data or "pages" in data:
        return {"ground_truth": data.get("ground_truth"), "pages": data.get("pages")}
    # A bare ground_truth object (brand_name/key_facts/...) was passed directly.
    return {"ground_truth": data, "pages": None}


def merge_mode(args):
    findings = load_findings(args.input)
    proactive = None
    if args.proactive and os.path.exists(args.proactive):
        with open(args.proactive, encoding="utf-8-sig") as f:
            proactive = json.load(f)
        if not isinstance(proactive, list):
            raise ValueError("--proactive file must contain a JSON array")

    context = load_context(getattr(args, "inventory", None))
    report = build_final_report(
        args.site,
        findings,
        proactive_recommendations=proactive,
        ground_truth=context["ground_truth"],
        pages=context["pages"],
    )
    output_text = json.dumps(report, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(json.dumps({"status": "written", "output": args.output, "finding_count": len(report["findings"])}, indent=2))
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
        action = f.get("suggested_action")
        if not isinstance(action, dict) or not all(action.get(x) for x in ("summary", "priority", "how_to_fix")):
            errors.append(f"finding {f.get('id', '?')} suggested_action requires summary, priority, how_to_fix")

    summary = report.get("summary", {})
    if isinstance(summary, dict):
        for sev in VALID_SEVERITIES:
            if not isinstance(summary.get(sev), int):
                errors.append(f"summary missing integer {sev} count")
        if summary.get("total_findings") != len(report.get("findings", [])):
            errors.append("summary total_findings does not match findings")

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
    merge_p.add_argument(
        "--inventory",
        help="Optional saved SiteInventory JSON (or bare ground_truth JSON) used to "
             "pre-populate suggested_action.fix_snippet for structured-data findings",
    )
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
