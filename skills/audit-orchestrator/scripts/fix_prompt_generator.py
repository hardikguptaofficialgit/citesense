"""Deterministic, evidence-bound implementation prompts for finalized findings."""
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

PROMPT_STATUSES = {"confirmed", "likely-risk", "proactive"}
PROMPT_PRIORITIES = {"critical", "high", "medium", "low"}
SUPPORTED_CATEGORIES = {
    "crawlability", "render-gap", "structured-data", "fact-extractability",
    "freshness", "internal-consistency", "corroboration", "entity-disambiguation",
    "orientation", "navigation", "personalization-readiness",
    "citation-omission", "citation-misattribution", "citation-staleness",
    "citation-contradiction",
}
REQUIRED_PROMPT_FIELDS = {
    "target", "prompt", "validation", "finding_id", "status", "priority", "evidence_refs",
    "suggested_action",
}
ROLE_BY_CATEGORY = {
    "crawlability": "technical SEO and platform engineer",
    "render-gap": "frontend and technical SEO engineer",
    "structured-data": "structured-data and technical SEO engineer",
    "fact-extractability": "content and frontend engineer",
    "freshness": "content operations owner",
    "internal-consistency": "content governance owner",
    "corroboration": "brand and digital-PR owner",
    "entity-disambiguation": "brand identity owner",
    "orientation": "UX and content designer",
    "navigation": "UX and frontend engineer",
    "personalization-readiness": "UX and product engineer",
    "citation-omission": "content and technical SEO owner",
    "citation-misattribution": "brand identity owner",
    "citation-staleness": "content operations owner",
    "citation-contradiction": "content governance owner",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _evidence_refs(finding: Dict[str, Any], ledger: Optional[Iterable[Dict[str, Any]]]) -> List[str]:
    refs = finding.get("evidence_refs")
    if not isinstance(refs, list):
        return []
    refs = [r for r in refs if isinstance(r, str) and r]
    if ledger is None:
        return refs
    available = {item.get("evidence_id") for item in ledger if isinstance(item, dict)}
    return [ref for ref in refs if ref in available]


def validate_fix_prompt(prompt: Dict[str, Any], finding: Optional[Dict[str, Any]] = None,
                        evidence_ledger: Optional[Iterable[Dict[str, Any]]] = None) -> List[str]:
    """Return validation errors; an empty list means the prompt is usable."""
    errors: List[str] = []
    if not isinstance(prompt, dict):
        return ["prompt must be an object"]
    missing = REQUIRED_PROMPT_FIELDS - set(prompt)
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if prompt.get("status") not in PROMPT_STATUSES:
        errors.append("unsupported status")
    if prompt.get("priority") not in PROMPT_PRIORITIES:
        errors.append("unsupported priority")
    if not isinstance(prompt.get("evidence_refs"), list) or not prompt.get("evidence_refs"):
        errors.append("evidence_refs must be a non-empty array")
    if evidence_ledger is not None:
        available = {item.get("evidence_id") for item in evidence_ledger if isinstance(item, dict)}
        if not set(prompt.get("evidence_refs", [])) <= available:
            errors.append("evidence_refs must resolve to the evidence ledger")
    for field in ("target", "prompt", "finding_id"):
        if not _text(prompt.get(field)):
            errors.append(f"{field} must be a non-empty string")
    if prompt.get("target") != "coding_agent":
        errors.append("target must be coding_agent")
    if not isinstance(prompt.get("validation"), list) or not all(
        _text(item) for item in prompt.get("validation", [])
    ):
        errors.append("validation must be a non-empty string array")
    if not isinstance(prompt.get("suggested_action"), dict):
        errors.append("suggested_action must be preserved as an object")
    if finding is not None:
        if prompt.get("finding_id") != finding.get("id"):
            errors.append("finding_id does not match finding")
        if prompt.get("suggested_action") != finding.get("suggested_action"):
            errors.append("suggested_action was not preserved")
        if prompt.get("evidence_refs") != _evidence_refs(finding, evidence_ledger):
            errors.append("evidence_refs do not match finding evidence")
    return errors


def is_valid_fix_prompt(prompt: Dict[str, Any], **kwargs: Any) -> bool:
    return not validate_fix_prompt(prompt, **kwargs)


def generate_fix_prompt(finding: Dict[str, Any],
                        evidence_ledger: Optional[Iterable[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Build one prompt, returning None for inconclusive/unsupported input."""
    if not isinstance(finding, dict):
        return None
    status, category = finding.get("status"), finding.get("category")
    action, refs = finding.get("suggested_action"), _evidence_refs(finding, evidence_ledger)
    evidence, title, finding_id = (_text(finding.get(k)) for k in ("evidence", "title", "id"))
    if status not in PROMPT_STATUSES or category not in SUPPORTED_CATEGORIES:
        return None
    if not (finding_id and title and evidence and refs and isinstance(action, dict)):
        return None
    if not all(_text(action.get(k)) for k in ("summary", "priority", "how_to_fix")):
        return None
    verify = status == "likely-risk"
    root_cause = (_text(finding.get("root_cause")) or
                  f"Use the observed condition described by “{title}” as the root-cause hypothesis; confirm it against the cited evidence.")
    role = ROLE_BY_CATEGORY[category]
    constraints = [
        "Do not invent facts, URLs, prices, contacts, schema values, or technologies.",
        "Use only information supported by the cited evidence refs.",
        "Preserve existing functionality and design unless this finding requires a content or design change.",
        "Do not make unrelated changes or remove valid metadata.",
        "Avoid duplicate or conflicting structured data and follow the site's existing architecture.",
        "Do not bypass robots.txt, authentication, WAF, anti-bot controls, or security boundaries.",
        "Review the change before applying it; this prompt is recommendation-only.",
    ]
    if verify:
        constraints.insert(0, "Treat this as a likely risk, not a confirmed defect; verify it before changing production.")
    elif status == "proactive":
        constraints.insert(0, "This is a proactive recommendation, not a detected defect; adopt it only if appropriate.")
    prompt_text = "\n\n".join([
        "ROLE\nYou are fixing a CiteSense website audit finding as a " + role + ".",
        f"PROBLEM\n{title}.",
        f"EVIDENCE\n{evidence}\nEvidence references: {', '.join(refs)}.",
        f"ROOT CAUSE\n{root_cause}",
        f"TASK\n{('First verify the condition using the cited evidence, then ' if verify else '')}{action['how_to_fix']}",
        "CONSTRAINTS\n" + "\n".join(f"- {item}" for item in constraints),
        "VALIDATION\n" + "\n".join([
            f"Re-run the check represented by finding {finding_id}.",
            "Confirm the reported condition is resolved using fresh evidence.",
            "Confirm no conflicting metadata or unrelated behavior was introduced.",
        ]),
    ])
    validation = [
        f"Re-run the check represented by finding {finding_id}.",
        "Confirm the reported condition is resolved using fresh evidence.",
        "Confirm no conflicting metadata or unrelated behavior was introduced.",
    ]
    prompt = {
        "target": "coding_agent",
        "prompt": prompt_text,
        "validation": validation,
        "finding_id": finding_id,
        "title": title,
        "status": status,
        "priority": action.get("priority", finding.get("severity")),
        "role": role,
        "problem": title,
        "evidence_refs": refs,
        "root_cause": root_cause,
        "task": ("First verify the condition using the cited evidence, then " if verify else "") + action["how_to_fix"],
        "constraints": constraints,
        "suggested_action": deepcopy(action),
    }
    return prompt if is_valid_fix_prompt(prompt, finding=finding, evidence_ledger=evidence_ledger) else None


def generate_fix_prompts(findings: Iterable[Dict[str, Any]],
                         evidence_ledger: Optional[Iterable[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    return [prompt for finding in findings
            for prompt in (generate_fix_prompt(finding, evidence_ledger),) if prompt is not None]


def build_fix_plan(prompts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create an execution-ordered plan while preserving finding priorities."""
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(
        enumerate(prompts),
        key=lambda pair: (
            priority_rank.get(pair[1].get("priority"), len(priority_rank)),
            pair[0],
        ),
    )
    plan = []
    for execution_order, (_input_order, prompt) in enumerate(ordered, start=1):
        plan.append({
            "finding_id": prompt["finding_id"],
            "execution_order": execution_order,
            "priority": prompt["priority"],
            "reason": (
                f"{prompt['status']} finding with existing {prompt['priority']} "
                "priority; resolve higher-impact findings first."
            ),
            "prompt": prompt["prompt"],
            "validation": prompt["validation"],
            "evidence_refs": prompt["evidence_refs"],
        })
    return plan
