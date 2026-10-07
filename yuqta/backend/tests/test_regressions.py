"""Bugs found in live testing; each test pins the fix."""

from fastapi.testclient import TestClient
import pytest

from app.db import meetings as repo
from app.main import app
from app.plugins.llm import get_llm_provider
from app.schemas.analysis import Evidence, Signal, SignalExtraction
from app.schemas.transcript import SegmentIn
from app.workflows.ingest_meeting import ingest_from_segments


class FixedLLM:
    """Returns the given signals for any transcript (stands in for a real model)."""

    name = "fixed"

    def __init__(self, *signals: Signal):
        self.signals = list(signals)

    def extract_signals(self, segments, known_customers):
        return SignalExtraction(provider=self.name, signals=self.signals)


def _evidence(index: int, quote: str) -> Evidence:
    return Evidence(segment_index=index, speaker="COO", quote=quote)


def _analyze(client: TestClient, llm: FixedLLM, lines: list[str]) -> dict:
    app.dependency_overrides[get_llm_provider] = lambda: llm
    meeting = client.post("/api/meetings", json={"title": "Check-in", "segments": [{"speaker": "COO", "text": t} for t in lines]}).json()
    response = client.post(f"/api/meetings/{meeting['id']}/analyze")
    assert response.status_code == 200, response.text
    return response.json()


def test_sales_claim_is_checked_against_revenue(seeded_api: TestClient) -> None:
    result = _analyze(seeded_api, FixedLLM(
        Signal(kind="metric_change", summary="Sales increased", metric="sales", direction="up", evidence=_evidence(0, "Sales are up."))
    ), ["Sales are up."])
    check = result["signals"][0]["data_check"]
    assert check["status"] == "contradicted"  # revenue actually fell 18.4%
    assert check["detail"] == "Revenue $2.39M → $1.95M (−$440K, −18.4%)"


def test_contradicted_statement_gets_a_correction_recommendation(seeded_api: TestClient) -> None:
    result = _analyze(seeded_api, FixedLLM(
        Signal(kind="order_change", summary="Gamma increased order volume", direction="up", customers=["Gamma"],
               evidence=_evidence(0, "Gamma increased their order volume again."))
    ), ["Gamma increased their order volume again."])
    [first, *_] = result["recommendations"]
    assert first["priority"] == "high"
    assert first["title"] == "Correct the record: Gamma increased order volume"
    assert first["owner"] == "Amit"
    assert first["rationale"] == [
        "Said in the meeting: “Gamma increased their order volume again.”",
        "The data shows: Gamma order units 800 → 700 (−12.5%)",
    ]


def test_headline_grammar_for_one_discussed_account(seeded_api: TestClient) -> None:
    result = _analyze(seeded_api, FixedLLM(
        Signal(kind="order_change", summary="Gamma reduced orders", direction="down", customers=["Gamma"],
               evidence=_evidence(0, "Gamma cut their order."))
    ), ["Gamma cut their order."])
    assert "Gamma (−$80K), discussed in the meeting, explains 18.2% of the decline." in result["summary"]["headline"]


def test_concurrent_import_of_same_transcript_returns_existing(seeded_db, monkeypatch: pytest.MonkeyPatch) -> None:
    segments = [SegmentIn(speaker="A", text="Revenue is down.")]
    with seeded_db() as db:
        first = ingest_from_segments(db, "First", [], segments, source="google_meet", external_ref="conferenceRecords/r/transcripts/t")
    # Simulate the race: the second request's duplicate check runs before the first one committed.
    real_find = repo.find_by_external_ref
    calls = {"n": 0}

    def racing_find(db, ref):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(db, ref)

    monkeypatch.setattr(repo, "find_by_external_ref", racing_find)
    with seeded_db() as db:
        second = ingest_from_segments(db, "Second", [], segments, source="google_meet", external_ref="conferenceRecords/r/transcripts/t")
    assert second.id == first.id and second.title == "First"


def test_agreed_action_gets_the_account_owner(seeded_api: TestClient) -> None:
    # The live case: a contradicted Gamma claim plus an agreed follow-up with Gamma.
    result = _analyze(seeded_api, FixedLLM(
        Signal(kind="order_change", summary="Gamma increased orders", direction="up", customers=["Gamma"],
               evidence=_evidence(0, "Gamma increased their order volume again.")),
        Signal(kind="action_item", summary="Follow up with Gamma next week", customers=["Gamma"], due="next week",
               evidence=_evidence(1, "Let's follow up with Gamma next week.")),
    ), ["Gamma increased their order volume again.", "Let's follow up with Gamma next week."])
    action = next(r for r in result["recommendations"] if r["title"] == "Follow up with Gamma next week")
    assert (action["owner"], action["customer"], action["due"]) == ("Amit", "Gamma", "next week")
