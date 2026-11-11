from pathlib import Path
import unittest

from app.insurance.review import compare_ocr_to_ground_truth


class ReviewTests(unittest.TestCase):
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
