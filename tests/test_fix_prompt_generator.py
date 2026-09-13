import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))

from compose_report import build_final_report
from fix_prompt_generator import (
    build_fix_plan,
    generate_fix_prompt,
    generate_fix_prompts,
    validate_fix_prompt,
)


def finding(status="confirmed", category="structured-data"):
    return {
        "id": "F-001",
        "title": "Missing observed structured data",
        "category": category,
        "severity": "medium",
        "status": status,
        "confidence": "high",
        "impact": "medium",
        "evidence": "Observed at https://acme.test/ via schema scan: no Organization block.",
        "evidence_refs": ["E-aaaaaaaaaaaa"],
        "evidence_details": {
            "evidence_id": "E-aaaaaaaaaaaa",
            "url": "https://acme.test/",
            "observation": "No Organization block.",
            "method": "schema scan",
            "timestamp": "2026-01-01T00:00:00Z",
            "confidence": "high",
        },
        "suggested_action": {
            "summary": "Add observed Organization structured data.",
            "priority": "medium",
            "how_to_fix": "Add an Organization JSON-LD block using verified site facts.",
        },
        "fingerprint": "schema:organization",
    }


class FixPromptTests(unittest.TestCase):
    ledger = [finding()["evidence_details"]]

    def test_supported_statuses_and_unsupported_statuses(self):
        for status in ("confirmed", "likely-risk", "proactive"):
            prompt = generate_fix_prompt(finding(status), self.ledger)
            self.assertIsNotNone(prompt)
            self.assertEqual(prompt["status"], status)
        for status in ("inconclusive", "not-assessed"):
            self.assertIsNone(generate_fix_prompt(finding(status), self.ledger))

    def test_traceability_and_likely_risk_guardrail(self):
        source = finding("likely-risk")
        prompt = generate_fix_prompt(source, self.ledger)
        self.assertEqual(prompt["evidence_refs"], source["evidence_refs"])
        self.assertEqual(prompt["suggested_action"], source["suggested_action"])
        self.assertIn("verify", prompt["task"].lower())
        self.assertTrue(any("likely risk" in c for c in prompt["constraints"]))

    def test_missing_evidence_rejects_prompt(self):
        source = finding()
        source["evidence_refs"] = []
        self.assertIsNone(generate_fix_prompt(source, self.ledger))
        source["evidence_refs"] = ["E-bbbbbbbbbbbb"]
        self.assertIsNone(generate_fix_prompt(source, self.ledger))

    def test_validation_rejects_malformed_prompt(self):
        self.assertTrue(validate_fix_prompt({}, evidence_ledger=self.ledger))
        prompt = generate_fix_prompt(finding(), self.ledger)
        prompt["evidence_refs"] = ["E-bbbbbbbbbbbb"]
        self.assertTrue(validate_fix_prompt(prompt, evidence_ledger=self.ledger))

    def test_composition_is_additive_and_keeps_ids_and_score_inputs(self):
        candidate = finding()
        before = copy.deepcopy(candidate)
        report = build_final_report("https://acme.test", [candidate])
        self.assertEqual(report["findings"][0]["id"], "F-001")
        self.assertIn("fix_plan", report)
        self.assertIn("fix_prompt", report["findings"][0])
        self.assertEqual(candidate["title"], before["title"])
        self.assertEqual(report["summary"]["total_findings"], 1)
        self.assertEqual(report["summary"]["medium"], 1)

    def test_legacy_finding_without_refs_remains_valid_without_prompt(self):
        source = finding()
        source.pop("evidence_refs")
        source.pop("evidence_details")
        report = build_final_report("https://acme.test", [source])
        self.assertNotIn("fix_plan", report)
        self.assertNotIn("fix_prompt", report["findings"][0])

    def test_fix_plan_preserves_priority_and_separates_execution_order(self):
        prompts = []
        for finding_id, priority in (("F-A", "medium"), ("F-B", "high"), ("F-C", "low")):
            source = finding()
            source["id"] = finding_id
            source["suggested_action"]["priority"] = priority
            prompts.append(generate_fix_prompt(source, self.ledger))

        plan = build_fix_plan(prompts)

        self.assertEqual([item["finding_id"] for item in plan], ["F-B", "F-A", "F-C"])
        self.assertEqual([item["execution_order"] for item in plan], [1, 2, 3])
        self.assertEqual([item["priority"] for item in plan], ["high", "medium", "low"])
        self.assertNotEqual(plan[0]["priority"], plan[0]["execution_order"])

    def test_fix_plan_keeps_stable_input_order_for_equal_priorities(self):
        prompts = []
        for finding_id in ("F-B", "F-A"):
            source = finding()
            source["id"] = finding_id
            source["suggested_action"]["priority"] = "high"
            prompts.append(generate_fix_prompt(source, self.ledger))

        plan = build_fix_plan(prompts)

        self.assertEqual([item["finding_id"] for item in plan], ["F-B", "F-A"])
        self.assertEqual([item["priority"] for item in plan], ["high", "high"])
        self.assertEqual([item["execution_order"] for item in plan], [1, 2])


if __name__ == "__main__":
    unittest.main()
