"""OpenRouter provider against a mock HTTP transport (no key, no network)."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.plugins.llm import LLMError, build_llm_provider
from app.plugins.llm.openrouter_provider import OpenRouterLLMProvider
from app.schemas.transcript import SegmentIn


SEGMENTS = [
    SegmentIn(speaker="Sales Manager", text="Enterprise revenue is down this month."),
    SegmentIn(speaker="Finance Manager", text="Acme reduced their order significantly."),
]
CUSTOMERS = ["Acme", "Beta", "Gamma"]


def _completion(signals: list[dict], finish_reason: str = "stop", model: str = "typesafe/jev-latest") -> dict:
    # Shape of an OpenRouter chat completion; structured output arrives as a JSON string in message.content.
    return {
        "id": "gen-123",
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": json.dumps({"signals": signals})}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }


SIGNALS = [
    {"kind": "metric_change", "summary": "Enterprise revenue reported down", "metric": "Revenue",
     "direction": "down", "customers": [], "due": None, "segment_index": 0},
    {"kind": "order_change", "summary": "Acme reduced orders", "metric": None,
     "direction": "down", "customers": ["ACME"], "due": None, "segment_index": 1},
    {"kind": "renewal_risk", "summary": "Zeta late", "metric": None,
     "direction": None, "customers": ["Zeta"], "due": None, "segment_index": 1},
]


def _provider(handler, model: str = "typesafe/jev-router") -> OpenRouterLLMProvider:
    return OpenRouterLLMProvider("sk-or-test", model, transport=httpx.MockTransport(handler))


def test_factory_and_config_validation() -> None:
    provider = build_llm_provider(
        Settings(_env_file=None, llm_provider="openrouter", llm_api_key="sk-or-x", llm_model="typesafe/jev-router")
    )
    assert isinstance(provider, OpenRouterLLMProvider) and provider.model == "typesafe/jev-router"
    with pytest.raises(LLMError, match="needs LLM_API_KEY"):
        build_llm_provider(Settings(_env_file=None, llm_provider="openrouter", llm_model="typesafe/jev-router"))
    with pytest.raises(LLMError, match="not an OpenRouter model id"):
        build_llm_provider(Settings(_env_file=None, llm_provider="openrouter", llm_api_key="sk-or-x", llm_model="claude-opus-5-5"))


def test_jev_router_is_the_default_model() -> None:
    provider = build_llm_provider(Settings(_env_file=None, llm_provider="openrouter", llm_api_key="sk-or-x"))
    assert provider.model == "typesafe/jev-router"


def test_anthropic_rejects_openrouter_model_id() -> None:
    with pytest.raises(LLMError, match="is an OpenRouter id"):
        build_llm_provider(Settings(_env_file=None, llm_provider="anthropic", llm_api_key="sk-ant-x"))


def test_request_shape_and_validated_signals() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
        return httpx.Response(200, json=_completion(SIGNALS))

    result = _provider(handler).extract_signals(SEGMENTS, CUSTOMERS)

    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test"
    body = seen["body"]
    assert body["model"] == "typesafe/jev-router"
    assert body["provider"] == {"require_parameters": True}
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["meeting", "signals"]
    signal_schema = schema["$defs"]["ExtractedSignal"]
    assert signal_schema["additionalProperties"] is False
    assert set(signal_schema["required"]) == set(signal_schema["properties"])
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "[1] Finance Manager: Acme reduced their order significantly." in body["messages"][1]["content"]

    assert result.provider == "openrouter:typesafe/jev-latest"  # the model the router actually used
    assert [(s.kind, s.customers, s.evidence.quote) for s in result.signals] == [
        ("metric_change", [], "Enterprise revenue is down this month."),
        ("order_change", ["Acme"], "Acme reduced their order significantly."),
    ]  # unknown customer "Zeta" dropped, "ACME" normalised
    assert result.signals[0].metric == "revenue"
    assert schema["$defs"]["ExtractedSignal"]["properties"]["metric"]["anyOf"][0]["enum"] == ["revenue", "sales", "margin", "pipeline"]


def test_qualified_metric_name_is_normalised() -> None:
    signal = dict(SIGNALS[0], metric="Enterprise Revenue")
    result = _provider(lambda request: httpx.Response(200, json=_completion([signal]))).extract_signals(SEGMENTS, CUSTOMERS)
    assert result.signals[0].metric == "revenue"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"error": {"code": 401, "message": "No auth credentials found"}}), "rejected the API key"),
        (httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits"}}), "insufficient credits"),
        (httpx.Response(429, json={"error": {"code": 429, "message": "Rate limited"}}), "rate limit"),
        (httpx.Response(404, json={"error": {"code": 404, "message": "No endpoints found that support the requested parameters"}}),
         "No endpoints found"),
        (httpx.Response(200, json={"error": {"code": 502, "message": "Upstream provider error"}}), "Upstream provider error"),
        (httpx.Response(200, json=_completion(SIGNALS, finish_reason="length")), "incomplete"),
        (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]}), "expected format"),
        (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": None}}]}), "no content"),
    ],
)
def test_errors(response: httpx.Response, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _provider(lambda request: response).extract_signals(SEGMENTS, CUSTOMERS)


def test_timeout() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError, match="timed out"):
        _provider(slow).extract_signals(SEGMENTS, CUSTOMERS)
