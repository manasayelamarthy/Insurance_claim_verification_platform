from pathlib import Path
import unittest

from app.insurance.ground_truth import load_user_claim_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CURATED_USERS = PROJECT_ROOT / "data" / "external" / "curated" / "users"


class InsuranceGroundTruthTests(unittest.TestCase):
    def test_loads_all_curated_user_bundles(self) -> None:
        users = sorted(CURATED_USERS.glob("user_*"))

        bundles = [load_user_claim_bundle(user) for user in users]

        self.assertEqual(len(bundles), 5)
        self.assertEqual(
            {bundle.hospital_bill.hospital.name for bundle in bundles},
            {
                "Lilavati Hospital",
                "Manipal Hospital",
                "Apollo Health City",
                "Christian Medical College (CMC)",
                "Fortis Escorts Heart Institute",
            },
        )
        for bundle in bundles:
            self.assertEqual(bundle.hospital_bill.patient, bundle.discharge_summary.patient)
            self.assertGreater(len(bundle.hospital_bill.procedures), 0)
