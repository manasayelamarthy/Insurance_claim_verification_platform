from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, request
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

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
    provider: str = "openai_compatible"


def load_settings() -> LLMSettings:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
        return LLMSettings(
            api_url=(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            ),
            api_key=gemini_key,
            model=model,
            provider="google",
        )

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
    system_prompt = (
        "You answer insurance policy questions using only the supplied policy "
        "evidence. Do not infer missing terms. If the evidence does not answer "
        "the question, say so. Cite every factual statement with the supplied "
        "[Page N; Section] marker."
    )
    if settings.provider == "google":
        return _answer_with_google(
            settings, question, evidence, system_prompt
        )

    payload = {
        "model": settings.model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
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
    except error.HTTPError as exc:
        raise LLMRequestError(
            provider_error_message("LLM provider", exc)
        ) from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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


def _answer_with_google(
    settings: LLMSettings, question: str, evidence: str, system_prompt: str
) -> str:
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"Question: {question}\n\nPolicy evidence:\n{evidence}"
                    }
                ],
            }
        ],
        "generationConfig": {"temperature": 0},
    }
    http_request = request.Request(
        f"{settings.api_url}?key={settings.api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=settings.timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise LLMRequestError(
            provider_error_message("Google Gemini", exc)
        ) from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMRequestError("The Google Gemini provider could not answer the question.") from exc

    try:
        answer = response_data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("Google Gemini returned an invalid response.") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise LLMRequestError("Google Gemini returned an empty answer.")
    if "[Page " not in answer:
        raise LLMRequestError("The LLM response did not include required page citations.")
    return answer.strip()


def provider_error_message(provider: str, http_error: error.HTTPError) -> str:
    """Return provider status and message without exposing request credentials."""
    try:
        response = json.loads(http_error.read().decode("utf-8"))
        message = response.get("error", {}).get("message")
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        message = None
    if not isinstance(message, str) or not message.strip():
        message = "The provider could not answer the question."
    return f"{provider} request failed ({http_error.code}): {message}"
