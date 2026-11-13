from pathlib import Path
import unittest

from app.insurance.documents import extract_document


ROOT = Path(__file__).resolve().parents[1]


class DocumentExtractionTests(unittest.TestCase):
    def test_extracts_text_from_claim_form(self) -> None:
        path = ROOT / "data" / "claims" / "claim_clm_1001" / "claim_form_CLM-1001.txt"

        document = extract_document(path)

        self.assertEqual(document.document_type, "text")
        self.assertIn("Claim Number: CLM-1001", document.text)

    def test_extracts_text_from_hospital_bill_pdf(self) -> None:
        path = ROOT / "data" / "claims" / "claim_clm_1001" / "hospital_bill_CLM-1001.pdf"

        document = extract_document(path)

        self.assertEqual(document.document_type, "pdf")
        self.assertIn("TOTAL CLAIMED", document.text)
