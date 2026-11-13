from pathlib import Path
import unittest

from app.insurance.decision import decide_claim, read_claim_form, read_hospital_bill, read_policy
from app.insurance.risk import assess_claim_risk


ROOT = Path(__file__).resolve().parents[1] / "data" / "claims"


class RiskTests(unittest.TestCase):
    def evaluate(self, folder: str):
        directory = ROOT / folder
        claim = read_claim_form(next(directory.glob("claim_form_*.txt")))
        claim = read_hospital_bill(next(directory.glob("hospital_bill_*.pdf")), claim)
        policy = read_policy(next(directory.glob("policy_*.txt")))
        return claim, policy, decide_claim(claim, policy)

    def test_clean_claim_has_no_findings(self) -> None:
        claim, policy, decision = self.evaluate("claim_clm_1001")

        assessment = assess_claim_risk(claim, policy, decision)

        self.assertEqual(assessment.risk_level, "low")
        self.assertFalse(assessment.manual_review_required)
        self.assertEqual(assessment.findings, ())

    def test_room_limit_is_flagged_for_manual_review(self) -> None:
        claim, policy, decision = self.evaluate("claim_clm_1002")

        assessment = assess_claim_risk(claim, policy, decision)

        self.assertEqual(assessment.risk_level, "medium")
        self.assertTrue(assessment.manual_review_required)
        self.assertIn("room_charge_anomaly", [finding.code for finding in assessment.findings])
