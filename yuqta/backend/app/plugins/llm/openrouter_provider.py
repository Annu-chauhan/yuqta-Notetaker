"""Signal extraction through OpenRouter (any model it hosts, e.g. typesafe/jev-router).

API: POST https://openrouter.ai/api/v1/chat/completions with `Authorization: Bearer <key>`.
Structured outputs: response_format json_schema (strict); require_parameters keeps routing to
providers that honour it. Docs: https://openrouter.ai/docs/features/structured-outputs
"""

from collections.abc import Sequence
import logging

import httpx
from pydantic import ValidationError

from app.plugins.llm.base import LLMError
from app.plugins.llm.extraction import SYSTEM_PROMPT, Extraction, strict_json_schema, user_prompt, validated_meeting, validated_signals
from app.schemas.analysis import SignalExtraction
from app.schemas.transcript import SegmentIn


logger = logging.getLogger(__name__)

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterLLMProvider:
    name = "openrouter"

    def __init__(self, api_key: str, model: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise LLMError("LLM_PROVIDER=openrouter needs LLM_API_KEY (your OpenRouter key, sk-or-...).")
        if "/" not in model:
            raise LLMError(
                f"LLM_MODEL={model!r} is not an OpenRouter model id. Use the form vendor/model, e.g. typesafe/jev-router."
            )
        self.model = model
        self._http = httpx.Client(
            timeout=httpx.Timeout(180.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                # Optional attribution headers OpenRouter shows in its dashboard.
                "X-Title": "Yuqta",
            },
            transport=transport,
        )

    def extract_signals(self, segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> SignalExtraction:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(segments, known_customers)},
            ],
            "max_tokens": 16000,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "signal_extraction", "strict": True, "schema": strict_json_schema()},
            },
            # Only route to providers that support structured outputs for this model.
            "provider": {"require_parameters": True},
        }
        try:
            response = self._http.post(CHAT_URL, json=body)
        except httpx.TimeoutException as error:
            raise LLMError("OpenRouter timed out.") from error
        except httpx.HTTPError as error:
            raise LLMError(f"Could not reach OpenRouter: {error.__class__.__name__}") from error

        payload = _json(response)
        if response.status_code == 401:
            raise LLMError("OpenRouter rejected the API key (check LLM_API_KEY).")
        if response.status_code == 402:
            raise LLMError("OpenRouter account has insufficient credits.")
        if response.status_code == 429:
            raise LLMError("OpenRouter rate limit reached; try again shortly.")
        if not response.is_success or "error" in payload:
            raise LLMError(f"OpenRouter error {response.status_code}: {_error_message(payload)}")

        choice = (payload.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("The model returned an incomplete result.")
        content = (choice.get("message") or {}).get("content")
        if not content:
            raise LLMError("The model returned no content.")
        try:
            extraction = Extraction.model_validate_json(content)
        except ValidationError as error:
            raise LLMError("The model's answer did not match the expected format.") from error

        signals = validated_signals(extraction, segments, known_customers)
        served_by = payload.get("model") or self.model
        logger.info("OpenRouter %s (served by %s) extracted %d signals", self.model, served_by, len(signals))
        return SignalExtraction(provider=f"{self.name}:{served_by}", signals=signals, meeting=validated_meeting(extraction.meeting, segments))


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {"error": {"message": response.text[:200] or "invalid response"}}
    return body if isinstance(body, dict) else {}


def _error_message(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "no details")[:300]
    return str(error or "no details")[:300]
