import unittest
from unittest.mock import patch

from app.insurance.llm import (
    LLMConfigurationError,
    LLMSettings,
    answer_with_llm,
    load_settings,
)
from app.insurance.policy_search import PolicySearchResult


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"choices": [{"message": {"content": "Covered. [Page 2; Waiting Period]"}}]}'


class LLMTests(unittest.TestCase):
    def test_requires_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LLMConfigurationError):
                load_settings()

    def test_loads_openai_compatible_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_API_KEY": "test-key",
                "LLM_API_URL": "http://localhost:11434/v1/chat/completions",
                "LLM_MODEL": "local-model",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.api_url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(settings.model, "local-model")

    @patch("app.insurance.llm.request.urlopen", return_value=FakeResponse())
    def test_sends_retrieved_evidence_to_llm(self, urlopen) -> None:
        result = PolicySearchResult(2, "Waiting Period", "Waiting period is 30 days.", 0.8)

        answer = answer_with_llm(
            "What is the waiting period?",
            [result],
            LLMSettings("http://provider.test/v1/chat/completions", "key", "model"),
        )

        self.assertIn("[Page 2", answer)
        payload = urlopen.call_args.args[0].data.decode("utf-8")
        self.assertIn("Waiting period is 30 days.", payload)
