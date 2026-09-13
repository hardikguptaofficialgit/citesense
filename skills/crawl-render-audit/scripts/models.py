"""
models.py -- Standardized data models for the brand-ai-readiness-audit system.
Defines CandidateFinding, EvidenceVerification, and validation helpers.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import json
import re
import hashlib

VALID_CATEGORIES = {
    "crawlability", "render-gap", "structured-data", "fact-extractability",
    "freshness", "internal-consistency", "corroboration", "entity-disambiguation",
    "orientation", "navigation", "personalization-readiness",
    "citation-omission", "citation-misattribution", "citation-staleness", "citation-contradiction"
}

DISCOVERABILITY_CATEGORIES = {
    "crawlability", "render-gap", "structured-data", "fact-extractability",
    "freshness", "internal-consistency", "corroboration", "entity-disambiguation",
    "citation-omission", "citation-misattribution", "citation-staleness", "citation-contradiction"
}

ENGAGEMENT_CATEGORIES = {
    "orientation", "navigation", "personalization-readiness"
}

VALID_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_STATUSES = {"confirmed", "likely-risk", "inconclusive", "not-assessed", "proactive"}
VALID_CONFIDENCES = {"high", "medium", "low"}
VALID_IMPACTS = {"critical", "high", "medium", "low"}


@dataclass
class EvidenceVerification:
    url: str
    observation: str
    method: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    confidence: str = "high"  # high, medium, low

    @property
    def evidence_id(self) -> str:
        """Return a stable reference for this observation across report composition."""
        stable = "|".join((self.url, self.method, self.observation, self.confidence))
        return "E-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]

    def format_text(self) -> str:
        """Formats evidence into a verifiable, human and machine-readable text block."""
        return (
            f"Observed at {self.url} via {self.method} [{self.timestamp}]: {self.observation} "
            f"(Confidence: {self.confidence})"
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["evidence_id"] = self.evidence_id
        return data


@dataclass
class SuggestedAction:
    summary: str
    priority: str  # critical, high, medium, low
    how_to_fix: str
    beyond_defect: bool = False
    expected_benefit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "summary": self.summary,
            "priority": self.priority,
            "how_to_fix": self.how_to_fix
        }
        if self.beyond_defect:
            d["beyond_defect"] = True
        if self.expected_benefit:
            d["expected_benefit"] = self.expected_benefit
        return d


@dataclass
class CandidateFinding:
    title: str
    category: str
    severity: str  # critical, high, medium, low
    evidence: str
    source_skill: str
    suggested_action: Dict[str, Any]
    fingerprint: Optional[str] = None
    status: str = "confirmed"  # confirmed, likely-risk, proactive
    confidence: str = "high"  # high, medium, low
    impact: str = "medium"  # critical, high, medium, low
    evidence_details: Optional[Dict[str, Any]] = None
    id: Optional[str] = None
    source_skills: Optional[List[str]] = None

    def __post_init__(self):
        if self.category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{self.category}'. Must be one of {VALID_CATEGORIES}")
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity '{self.severity}'. Must be one of {VALID_SEVERITIES}")
        if self.status not in VALID_STATUSES:
            self.status = "confirmed"
        if self.confidence not in VALID_CONFIDENCES:
            self.confidence = "high"
        if self.impact not in VALID_IMPACTS:
            self.impact = self.severity
        if not self.fingerprint:
            norm_title = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
            self.fingerprint = f"{self.category}:{norm_title}"
        if not self.source_skills and self.source_skill:
            self.source_skills = [self.source_skill]

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "confidence": self.confidence,
            "impact": self.impact,
            "evidence": self.evidence,
            "source_skill": self.source_skill,
            "fingerprint": self.fingerprint,
            "suggested_action": self.suggested_action,
        }
        if self.id:
            out["id"] = self.id
        if self.source_skills:
            out["source_skills"] = self.source_skills
        if self.evidence_details:
            out["evidence_details"] = self.evidence_details
            evidence_id = self.evidence_details.get("evidence_id")
            if evidence_id:
                out["evidence_refs"] = [evidence_id]
        return out


def create_candidate_finding(
    title: str,
    category: str,
    severity: str,
    url: str,
    observation: str,
    method: str,
    source_skill: str,
    action_summary: str,
    action_priority: str,
    action_how_to_fix: str,
    fingerprint: Optional[str] = None,
    status: str = "confirmed",
    confidence: str = "high",
    impact: Optional[str] = None,
    beyond_defect: bool = False,
    expected_benefit: Optional[str] = None
) -> CandidateFinding:
    ev_ver = EvidenceVerification(
        url=url,
        observation=observation,
        method=method,
        confidence=confidence
    )
    formatted_evidence = ev_ver.format_text()
    
    action = SuggestedAction(
        summary=action_summary,
        priority=action_priority,
        how_to_fix=action_how_to_fix,
        beyond_defect=beyond_defect,
        expected_benefit=expected_benefit or (
            f"Improves {category.replace('-', ' ')} by making the observed information "
            "clearer and more extractable for the intended audience."
        )
    ).to_dict()

    return CandidateFinding(
        title=title,
        category=category,
        severity=severity,
        evidence=formatted_evidence,
        source_skill=source_skill,
        suggested_action=action,
        fingerprint=fingerprint,
        status=status,
        confidence=confidence,
        impact=impact or severity,
        evidence_details=ev_ver.to_dict()
    )
