from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, request

from app.insurance.policy_search import PolicySearchResult


class LLMConfigurationError(RuntimeError):
    """Raised when the grounded answer model is not configured."""


class LLMRequestError(RuntimeError):
    """Raised when the model provider rejects or cannot answer a request."""


@dataclass(frozen=True)
class LLMSettings:
    api_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30


def load_settings() -> LLMSettings:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise LLMConfigurationError(
            "LLM_API_KEY is not configured. Configure an OpenAI-compatible provider."
        )
    return LLMSettings(
        api_url=os.getenv(
            "LLM_API_URL", "https://api.openai.com/v1/chat/completions"
        ).strip(),
        api_key=api_key,
        model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
    )


def answer_with_llm(
    question: str,
    results: list[PolicySearchResult],
    settings: LLMSettings | None = None,
) -> str:
    if not results:
        raise LLMRequestError("Cannot ask the LLM without retrieved policy evidence.")
    settings = settings or load_settings()
    evidence = "\n\n".join(
        f"[Page {result.page_number}; {result.section}]\n{result.text}"
        for result in results
    )
    payload = {
        "model": settings.model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You answer insurance policy questions using only the supplied "
                    "policy evidence. Do not infer missing terms. If the evidence "
                    "does not answer the question, say so. Cite every factual "
                    "statement with the supplied [Page N; Section] marker."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\nPolicy evidence:\n{evidence}",
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        settings.api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=settings.timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMRequestError("The LLM provider could not answer the question.") from exc

    try:
        answer = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("The LLM provider returned an invalid response.") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise LLMRequestError("The LLM provider returned an empty answer.")
    if "[Page " not in answer:
        raise LLMRequestError("The LLM response did not include required page citations.")
    return answer.strip()
