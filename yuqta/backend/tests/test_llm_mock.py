import json
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.plugins.llm import LLMError, MockLLMProvider, build_llm_provider
from app.schemas.transcript import SegmentIn


CUSTOMERS = ["Acme", "Beta", "Gamma"]


def _sample_segments() -> list[SegmentIn]:
    fixture = json.loads(Path(get_settings().sample_transcript_path).read_text(encoding="utf-8"))
    return [SegmentIn.model_validate(segment) for segment in fixture["segments"]]


def _extract(*lines: tuple[str, str]):
    return MockLLMProvider().extract_signals([SegmentIn(speaker=s, text=t) for s, t in lines], CUSTOMERS).signals


def test_factory_mock_default_and_others_unavailable() -> None:
    assert isinstance(build_llm_provider(Settings(_env_file=None)), MockLLMProvider)
    with pytest.raises(LLMError, match="Unknown LLM_PROVIDER"):
        build_llm_provider(Settings(_env_file=None, llm_provider="unknown"))


def test_sample_meeting_signals() -> None:
    result = MockLLMProvider().extract_signals(_sample_segments(), CUSTOMERS)
    assert result.provider == "mock"
    assert [(s.kind, s.summary, s.customers, s.evidence.segment_index) for s in result.signals] == [
        ("metric_change", "Enterprise revenue reported down", [], 0),
        ("order_change", "Acme reduced orders", ["Acme"], 1),
        ("renewal_risk", "Beta has not renewed", ["Beta"], 2),
        ("action_item", "Contact Acme and Beta this week", ["Acme", "Beta"], 3),
    ]
    assert result.signals[0].metric == "revenue" and result.signals[0].direction == "down"
    assert result.signals[3].due == "this week"
    assert result.signals[1].evidence.speaker == "Finance Manager"
    assert result.signals[1].evidence.quote == "Acme reduced their order significantly."


def test_same_input_same_output() -> None:
    first = MockLLMProvider().extract_signals(_sample_segments(), CUSTOMERS)
    second = MockLLMProvider().extract_signals(_sample_segments(), CUSTOMERS)
    assert first == second


def test_revenue_up_and_order_increase() -> None:
    signals = _extract(("CFO", "Revenue grew this quarter."), ("Sales", "Gamma increased their order volume."))
    assert [(s.kind, s.direction, s.customers) for s in signals] == [
        ("metric_change", "up", []),
        ("order_change", "up", ["Gamma"]),
    ]


def test_renewed_customer_is_not_a_risk_and_unknown_names_ignored() -> None:
    assert _extract(("PM", "Gamma renewed last month."), ("PM", "Zeta reduced their order.")) == []


def test_action_without_known_customers() -> None:
    [signal] = _extract(("Lead", "We will follow up next week."))
    assert (signal.kind, signal.summary, signal.customers, signal.due) == (
        "action_item",
        "Follow-up action agreed next week",
        [],
        "next week",
    )
