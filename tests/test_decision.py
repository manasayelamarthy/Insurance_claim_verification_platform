import json
from pathlib import Path
import unittest

from app.insurance.decision import (
    decide_claim,
    read_claim_form,
    read_hospital_bill,
    read_policy,
)


ROOT = Path(__file__).resolve().parents[1] / "data" / "claims"


class DecisionTests(unittest.TestCase):
    def evaluate(self, folder: str):
        directory = ROOT / folder
        claim = read_claim_form(next(directory.glob("claim_form_*.txt")))
        claim = read_hospital_bill(next(directory.glob("hospital_bill_*.pdf")), claim)
        policy = read_policy(next(directory.glob("policy_*.txt")))
        return claim, decide_claim(claim, policy)

    def test_eligible_claim(self) -> None:
        claim, decision = self.evaluate("claim_clm_1001")
        self.assertEqual(claim.claim_number, "CLM-1001")
        self.assertEqual(decision.decision, "eligible")
        self.assertEqual(decision.payable_amount, 42000)

    def test_partially_eligible_claim_applies_copayment(self) -> None:
        _, decision = self.evaluate("claim_clm_1002")
        self.assertEqual(decision.decision, "partially_eligible")
        self.assertEqual(decision.eligible_amount_before_copay, 65000)
        self.assertEqual(decision.payable_amount, 52000)

    def test_excluded_claim_is_not_eligible(self) -> None:
        _, decision = self.evaluate("claim_clm_1003")
        self.assertEqual(decision.decision, "not_eligible")
        self.assertEqual(decision.payable_amount, 0)
        self.assertTrue(any("excluded" in reason for reason in decision.reasons))
