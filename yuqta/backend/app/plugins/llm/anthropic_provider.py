"""Claude-backed signal extraction via the official Anthropic SDK (structured outputs)."""

from collections.abc import Sequence
import logging
from typing import Any

import anthropic

from app.plugins.llm.base import LLMError
from app.plugins.llm.extraction import SYSTEM_PROMPT, Extraction, ExtractedSignal, user_prompt, validated_meeting, validated_signals
from app.schemas.analysis import SignalExtraction
from app.schemas.transcript import SegmentIn


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

# Kept for callers that import the schema from here.
_Extraction, _ExtractedSignal = Extraction, ExtractedSignal


class AnthropicLLMProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str = DEFAULT_MODEL, effort: str = "medium", client: Any = None):
        self.model = model
        self.effort = effort
        try:
            # Without an explicit key the SDK resolves ANTHROPIC_API_KEY / an `ant auth login` profile.
            self.client = client or anthropic.Anthropic(api_key=api_key or None, max_retries=2, timeout=120.0)
        except anthropic.AnthropicError as error:
            raise LLMError("No Anthropic credentials. Set LLM_API_KEY (or ANTHROPIC_API_KEY).") from error

    def extract_signals(self, segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> SignalExtraction:
        prompt = user_prompt(segments, known_customers)
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=Extraction,
                output_config={"effort": self.effort},
                # Server-side refusal fallback: on a policy decline the API retries on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as error:
            raise LLMError("Anthropic rejected the API key (check LLM_API_KEY).") from error
        except anthropic.RateLimitError as error:
            raise LLMError("Anthropic rate limit reached; try again shortly.") from error
        except anthropic.APIStatusError as error:
            raise LLMError(f"Anthropic API error {error.status_code}: {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise LLMError("Could not reach the Anthropic API.") from error

        if response.stop_reason == "refusal":
            raise LLMError("The model declined to analyze this transcript.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("The model returned an incomplete result.")

        signals = validated_signals(response.parsed_output, segments, known_customers)
        logger.info("Anthropic %s extracted %d signals (request %s)", self.model, len(signals), response._request_id)
        return SignalExtraction(provider=f"{self.name}:{self.model}", signals=signals, meeting=validated_meeting(response.parsed_output.meeting, segments))
