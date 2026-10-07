from uuid import uuid4

from fastapi.testclient import TestClient

from app.analytics.formatting import pct, usd
from app.main import app
from app.plugins.llm import LLMError, get_llm_provider


def _analyzed(client: TestClient) -> tuple[str, dict]:
    meeting_id = client.post("/api/meetings/sample").json()["id"]
    response = client.post(f"/api/meetings/{meeting_id}/analyze")
    assert response.status_code == 200, response.text
    return meeting_id, response.json()


def test_formatting_helpers() -> None:
    assert usd(2390000) == "$2.39M"
    assert usd(1950000) == "$1.95M"
    assert usd(-440000) == "−$440K"
    assert usd(1500000) == "$1.5M"
    assert pct(-18.41) == "−18.4%"


def test_sample_analysis_end_to_end(seeded_api: TestClient) -> None:
    meeting_id, result = _analyzed(seeded_api)

    assert result["status"] == "analyzed"
    assert result["llm_provider"] == "mock"
    assert result["periods"] == {"previous": "2026-08-01", "current": "2026-09-01"}

    checks = {s["summary"]: (s["data_check"]["status"], s["data_check"]["detail"]) for s in result["signals"]}
    assert checks == {
        "Enterprise revenue reported down": ("confirmed", "Revenue $2.39M → $1.95M (−$440K, −18.4%)"),
        "Acme reduced orders": ("confirmed", "Acme order units 1,000 → 690 (−31.0%)"),
        "Beta has not renewed": ("confirmed", "Beta renewal overdue since 15 Sep 2026 ($1.5M contract)"),
        "Contact Acme and Beta this week": ("confirmed", "Acme: At Risk, owner Rahul; Beta: At Risk, owner Priya"),
    }

    kpis = {k["key"]: k for k in result["kpis"]}
    assert list(kpis) == ["revenue", "order_volume:Acme", "renewal:Beta"]
    assert (kpis["revenue"]["previous"], kpis["revenue"]["current"]) == (2390000, 1950000)
    assert (kpis["revenue"]["change"], kpis["revenue"]["change_pct"]) == (-440000, -18.4)
    assert (kpis["order_volume:Acme"]["previous"], kpis["order_volume:Acme"]["current"]) == (1000, 690)
    assert kpis["order_volume:Acme"]["change_pct"] == -31.0
    assert kpis["renewal:Beta"]["value"] == "overdue"

    causes = [(c["rank"], c["segment"], c["contribution"], c["share_of_decline_pct"], c["mentioned_in_meeting"]) for c in result["root_causes"]]
    assert causes == [
        (1, "Acme", -190000, 43.2, True),
        (2, "Beta", -120000, 27.3, True),
        (3, "Gamma", -80000, 18.2, False),
        (4, "Other", -50000, 11.4, False),
    ]
    drivers = {c["segment"]: c["drivers"] for c in result["root_causes"]}
    assert drivers["Acme"] == ["Order volume −31.0% (1,000 → 690 units)"]
    assert drivers["Beta"] == [
        "Order volume −21.7% (600 → 470 units)",
        "Renewal overdue since 15 Sep 2026 ($1.5M contract)",
    ]
    assert drivers["Other"] == ["Long-tail accounts (no customer-level data)"]
    assert result["root_causes"][0]["evidence"][0]["quote"] == "Acme reduced their order significantly."

    assert result["summary"] == {
        "headline": "Revenue down $440K (−18.4%). Acme (−$190K) and Beta (−$120K), discussed in the meeting, "
        "explain 70.5% of the decline. Not discussed: Gamma (−$80K).",
        "revenue_change": -440000,
        "revenue_change_pct": -18.4,
        "explained_by_discussed_pct": 70.5,
        "not_discussed": ["Gamma"],
    }

    meeting = seeded_api.get(f"/api/meetings/{meeting_id}").json()
    assert meeting["status"] == "analyzed"


def test_stored_analysis_matches_and_reanalysis_is_idempotent(seeded_api: TestClient, seeded_db) -> None:
    from sqlalchemy import func, select

    from app.db.models import MeetingInsight

    meeting_id, first = _analyzed(seeded_api)
    stored = seeded_api.get(f"/api/meetings/{meeting_id}/analysis")
    assert stored.status_code == 200
    assert stored.json() == first

    second = seeded_api.post(f"/api/meetings/{meeting_id}/analyze").json()
    assert second == first
    with seeded_db() as session:
        count = session.scalar(select(func.count()).select_from(MeetingInsight))
    assert count == 1 + 4 + 3 + 4 + 4  # summary + signals + KPIs + root causes + recommendations, not doubled


def test_analysis_not_found_cases(seeded_api: TestClient) -> None:
    assert seeded_api.post(f"/api/meetings/{uuid4()}/analyze").status_code == 404
    assert seeded_api.get(f"/api/meetings/{uuid4()}/analysis").status_code == 404
    meeting_id = seeded_api.post("/api/meetings/sample").json()["id"]
    response = seeded_api.get(f"/api/meetings/{meeting_id}/analysis")
    assert (response.status_code, response.json()["detail"]) == (404, "Meeting has not been analyzed yet")


def test_meeting_without_transcript_cannot_be_analyzed(seeded_api: TestClient) -> None:
    from app.plugins.stt import STTError, get_sample_stt_provider

    class FailingSTT:
        name = "mock"

        def transcribe(self, audio):
            raise STTError("no audio")

    app.dependency_overrides[get_sample_stt_provider] = lambda: FailingSTT()
    seeded_api.post("/api/meetings/sample")
    del app.dependency_overrides[get_sample_stt_provider]
    failed_id = seeded_api.get("/api/meetings").json()[0]["id"]
    response = seeded_api.post(f"/api/meetings/{failed_id}/analyze")
    assert (response.status_code, response.json()["detail"]) == (409, "Meeting has no transcript to analyze.")


def test_without_business_data_the_meeting_is_analyzed_on_its_own(api: TestClient) -> None:
    meeting_id = api.post("/api/meetings/sample").json()["id"]
    response = api.post(f"/api/meetings/{meeting_id}/analyze")
    assert response.status_code == 200
    result = response.json()
    assert result["business_context"] is False and result["periods"] is None
    assert result["kpis"] == [] and result["root_causes"] == []
    assert result["summary"]["headline"] == result["meeting"]["summary"]
    # No customers are known, so only the company-level revenue line and the follow-up are signals; none is checked.
    assert {s["data_check"]["status"] for s in result["signals"]} == {"no_data"}
    assert [p["speaker"] for p in result["meeting"]["participation"]] == ["Sales Manager", "Finance Manager", "Product Manager"]
    assert ("high", "We should contact both customers this week", "this week") in [
        (r["priority"], r["title"], r["due"]) for r in result["recommendations"]
    ]
    spec = api.get(f"/api/meetings/{meeting_id}/dashboard").json()
    assert spec["periods"] is None
    assert [w.get("id", w["type"]) for w in spec["widgets"]] == ["summary", "kpis", "participation", "recommendations"]


def test_llm_failure_is_502_and_keeps_transcript(seeded_api: TestClient) -> None:
    class FailingLLM:
        name = "broken"

        def extract_signals(self, segments, known_customers):
            raise LLMError("model timed out")

    meeting_id = seeded_api.post("/api/meetings/sample").json()["id"]
    app.dependency_overrides[get_llm_provider] = lambda: FailingLLM()
    response = seeded_api.post(f"/api/meetings/{meeting_id}/analyze")
    assert (response.status_code, response.json()["detail"]) == (502, "Signal extraction failed: model timed out")
    meeting = seeded_api.get(f"/api/meetings/{meeting_id}").json()
    assert (meeting["status"], meeting["segment_count"]) == ("transcribed", 4)


def test_unavailable_llm_provider_is_503(seeded_api: TestClient, monkeypatch) -> None:
    from app.core import config

    meeting_id = seeded_api.post("/api/meetings/sample").json()["id"]
    monkeypatch.setattr(config.get_settings(), "llm_provider", "unknown")
    response = seeded_api.post(f"/api/meetings/{meeting_id}/analyze")
    assert response.status_code == 503
    assert "Unknown LLM_PROVIDER" in response.json()["detail"]
