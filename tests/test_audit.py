from pathlib import Path
import tempfile
import unittest

from app.insurance.audit import list_review_actions, record_review_action


class AuditTests(unittest.TestCase):
    def test_records_and_lists_review_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "audit.sqlite3"
            action = record_review_action(
                database, "CLM-1001", "approved", "employee-1", "Verified documents."
            )

            actions = list_review_actions(database, "CLM-1001")

            self.assertEqual(action.action, "approved")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].reviewer_id, "employee-1")

    def test_rejection_requires_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                record_review_action(
                    Path(directory) / "audit.sqlite3",
                    "CLM-1001",
                    "rejected",
                    "employee-1",
                    "",
                )
