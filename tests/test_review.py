from pathlib import Path
import unittest

from app.insurance.review import compare_ocr_to_ground_truth
from app.web import claim_decision, list_claims


class ReviewTests(unittest.TestCase):
    def test_claim_api_returns_all_synthetic_scenarios(self) -> None:
        self.assertEqual([claim["claim_id"] for claim in list_claims()], [
            "CLM-1001",
            "CLM-1002",
            "CLM-1003",
        ])

    def test_claim_api_returns_payable_amount(self) -> None:
        result = claim_decision("CLM-1001")
        self.assertEqual(result["decision"], "eligible")
        self.assertEqual(result["payable_amount"], "42000.00")

    def test_ocr_identity_checks(self) -> None:
        checks = compare_ocr_to_ground_truth(
            "Patient Amit Singh at Lilavati Hospital. Diagnosis Hyperlipidemia.",
            "Amit Singh",
            "Lilavati Hospital",
            "Hyperlipidemia",
        )

        self.assertTrue(all(check["matched"] for check in checks))

    def test_ocr_mismatch_is_reported(self) -> None:
        checks = compare_ocr_to_ground_truth(
            "Patient Unknown at Another Hospital.",
            "Amit Singh",
            "Lilavati Hospital",
            "Hyperlipidemia",
        )

        self.assertFalse(any(check["matched"] for check in checks))
