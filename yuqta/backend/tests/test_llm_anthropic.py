"""AnthropicLLMProvider with a fake SDK client (no network, no API key)."""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.core.config import Settings
from app.plugins.llm import LLMError, build_llm_provider
from app.plugins.llm.anthropic_provider import AnthropicLLMProvider, _Extraction, _ExtractedSignal
from app.schemas.transcript import SegmentIn


SEGMENTS = [
    SegmentIn(speaker="Sales Manager", text="Enterprise revenue is down this month."),
    SegmentIn(speaker="Finance Manager", text="Acme reduced their order significantly."),
    SegmentIn(speaker="Product Manager", text="Beta also hasn't renewed yet."),
    SegmentIn(speaker="Sales Manager", text="We should contact both customers this week."),
]
CUSTOMERS = ["Acme", "Beta", "Gamma"]


def _signal(**fields) -> _ExtractedSignal:
    base = {"metric": None, "direction": None, "customers": [], "due": None}
    return _ExtractedSignal(**{**base, **fields})


class FakeClient:
    def __init__(self, signals=(), stop_reason="end_turn", error: Exception | None = None):
        self.calls: list[dict] = []
        self._signals, self._stop_reason, self._error = list(signals), stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        parsed = _Extraction(signals=self._signals) if self._stop_reason == "end_turn" else None
        return SimpleNamespace(parsed_output=parsed, stop_reason=self._stop_reason, _request_id="req_test")


def _provider(client: FakeClient) -> AnthropicLLMProvider:
    return AnthropicLLMProvider(api_key="test-key", client=client)


def test_factory_builds_anthropic_provider_with_settings() -> None:
    provider = build_llm_provider(
        Settings(_env_file=None, llm_provider="anthropic", llm_api_key="sk-test", llm_model="claude-sonnet-5-5", llm_effort="low")
    )
    assert isinstance(provider, AnthropicLLMProvider)
    assert (provider.model, provider.effort) == ("claude-sonnet-5-5", "low")


def test_request_uses_structured_output_and_fallbacks() -> None:
    client = FakeClient()
    _provider(client).extract_signals(SEGMENTS, CUSTOMERS)
    [call] = client.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is _Extraction
    assert call["output_config"] == {"effort": "medium"}
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    prompt = call["messages"][0]["content"]
    assert "Known customers: Acme, Beta, Gamma" in prompt
    assert "[1] Finance Manager: Acme reduced their order significantly." in prompt


def test_signals_are_mapped_and_quotes_come_from_transcript() -> None:
    client = FakeClient(
        signals=[
            _signal(kind="metric_change", summary="Enterprise revenue reported down", metric="Revenue", direction="down", segment_index=0),
            _signal(kind="order_change", summary="Acme reduced orders", direction="down", customers=["acme"], segment_index=1),
            _signal(kind="renewal_risk", summary="Beta has not renewed", customers=["Beta"], segment_index=2),
            _signal(kind="action_item", summary="Contact Acme and Beta this week", customers=["Acme", "Beta"], due="This Week", segment_index=3),
        ]
    )
    result = _provider(client).extract_signals(SEGMENTS, CUSTOMERS)
    assert result.provider == "anthropic:claude-opus-5-5"
    assert [(s.kind, s.customers, s.evidence.segment_index) for s in result.signals] == [
        ("metric_change", [], 0),
        ("order_change", ["Acme"], 1),  # case-normalised to the known name
        ("renewal_risk", ["Beta"], 2),
        ("action_item", ["Acme", "Beta"], 3),
    ]
    assert result.signals[0].metric == "revenue"
    assert result.signals[3].due == "this week"
    assert result.signals[1].evidence.quote == "Acme reduced their order significantly."
    assert result.signals[1].evidence.speaker == "Finance Manager"


def test_untrusted_output_is_filtered() -> None:
    client = FakeClient(
        signals=[
            _signal(kind="order_change", summary="Zeta cut orders", direction="down", customers=["Zeta"], segment_index=1),
            _signal(kind="renewal_risk", summary="Beta late", customers=["Beta"], segment_index=99),
            _signal(kind="metric_change", summary="Revenue down", metric="revenue", direction="down", customers=["Acme"], due="now", segment_index=0),
        ]
    )
    signals = _provider(client).extract_signals(SEGMENTS, CUSTOMERS).signals
    assert len(signals) == 1  # unknown customer and out-of-range line dropped
    assert signals[0].kind == "metric_change"
    assert signals[0].due is None  # due only applies to action items


@pytest.mark.parametrize(
    ("stop_reason", "message"),
    [("refusal", "declined"), ("max_tokens", "incomplete")],
)
def test_refusal_and_truncation_raise(stop_reason: str, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _provider(FakeClient(stop_reason=stop_reason)).extract_signals(SEGMENTS, CUSTOMERS)


def _status_error(cls, status: int):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("error", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (lambda: _status_error(anthropic.AuthenticationError, 401), "rejected the API key"),
        (lambda: _status_error(anthropic.RateLimitError, 429), "rate limit"),
        (lambda: _status_error(anthropic.InternalServerError, 500), "API error 500"),
        (lambda: anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "Could not reach"),
    ],
)
def test_sdk_errors_become_llm_errors(error, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _provider(FakeClient(error=error())).extract_signals(SEGMENTS, CUSTOMERS)


def test_real_sdk_round_trip_over_mock_http() -> None:
    """Runs the real Anthropic SDK (schema generation, request, response parsing) against a canned HTTP reply."""
    import json

    import httpx2

    captured: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        payload = {
            "signals": [
                {"kind": "order_change", "summary": "Acme reduced orders", "metric": None, "direction": "down",
                 "customers": ["Acme"], "due": None, "segment_index": 1}
            ]
        }
        return httpx2.Response(
            200,
            headers={"request-id": "req_mock"},
            json={
                "id": "msg_mock", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 40},
            },
        )

    client = anthropic.Anthropic(
        api_key="sk-test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    result = AnthropicLLMProvider(api_key="sk-test", client=client).extract_signals(SEGMENTS, CUSTOMERS)

    assert [(s.kind, s.customers, s.evidence.quote) for s in result.signals] == [
        ("order_change", ["Acme"], "Acme reduced their order significantly.")
    ]
    body = captured["body"]
    assert captured["url"].endswith("/v1/messages?beta=true")
    assert "server-side-fallback-2026-07-01" in captured["headers"]["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "signals" in body["output_config"]["format"]["schema"]["properties"]
