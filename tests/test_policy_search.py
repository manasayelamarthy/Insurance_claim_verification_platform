from pathlib import Path
import unittest

from app.insurance.policy_search import answer_policy, chunk_policy, search_policy


ROOT = Path(__file__).resolve().parents[1]
POLICY = (
    ROOT
    / "data"
    / "external"
    / "curated"
    / "policies"
    / "hdfc-ergo"
    / "energy-diabetes-hypertension__wordings.pdf"
)


class PolicySearchTests(unittest.TestCase):
    def test_chunks_policy_with_page_numbers(self) -> None:
        chunks = chunk_policy(POLICY)

        self.assertGreater(len(chunks), 0)
        self.assertGreaterEqual(chunks[0].page_number, 1)
        self.assertGreater(chunks[0].token_count, 0)
        self.assertLessEqual(chunks[0].token_count, 500)

    def test_finds_relevant_policy_clause(self) -> None:
        results = search_policy(POLICY, "What is the waiting period?")

        self.assertGreater(len(results), 0)
        self.assertIn("waiting", results[0].text.lower())
        self.assertGreater(results[0].score, 0)
        self.assertTrue(results[0].section)

    def test_answers_with_citations_from_retrieved_clauses(self) -> None:
        response = answer_policy(POLICY, "What is the waiting period?")

        self.assertTrue(response.grounded)
        self.assertIn("Page", response.answer)
        self.assertGreater(len(response.citations), 0)
        self.assertIn("page_number", response.citations[0])

    def test_reports_when_policy_has_no_matching_evidence(self) -> None:
        response = answer_policy(POLICY, "What is zyxwv blorp?")

        self.assertFalse(response.grounded)
        self.assertEqual(response.citations, ())
