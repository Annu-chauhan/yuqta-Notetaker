from uuid import uuid4

from fastapi.testclient import TestClient


def _analyze_sample(client: TestClient) -> tuple[str, dict]:
    meeting_id = client.post("/api/meetings/sample").json()["id"]
    response = client.post(f"/api/meetings/{meeting_id}/analyze")
    assert response.status_code == 200, response.text
    return meeting_id, response.json()


def test_sample_recommendations(seeded_api: TestClient) -> None:
    _, result = _analyze_sample(seeded_api)
    recs = [(r["priority"], r["title"], r["owner"], r["due"]) for r in result["recommendations"]]
    assert recs == [
        ("high", "Contact Acme about reduced orders", "Rahul", "this week"),
        ("high", "Escalate Beta's overdue renewal", "Priya", "this week"),
        ("medium", "Review Gamma's revenue decline", "Amit", None),
        ("low", "Review long-tail accounts", None, None),
    ]
    acme, beta, gamma, _ = result["recommendations"]
    assert acme["rationale"] == ["Acme order units 1,000 → 690 (−31.0%)", "Revenue −$190K (43.2% of the decline)"]
    assert [e["quote"] for e in acme["evidence"]] == [
        "Acme reduced their order significantly.",
        "We should contact both customers this week.",
    ]
    assert beta["rationale"] == [
        "Beta renewal overdue since 15 Sep 2026 ($1.5M contract)",
        "Revenue −$120K (27.3% of the decline)",
    ]
    assert gamma["rationale"][:2] == ["Revenue −$80K (18.2% of the decline)", "Not discussed in the meeting"]
    assert gamma["evidence"] == []


def test_recommendations_are_stored(seeded_api: TestClient) -> None:
    meeting_id, result = _analyze_sample(seeded_api)
    stored = seeded_api.get(f"/api/meetings/{meeting_id}/analysis").json()
    assert stored["recommendations"] == result["recommendations"]


def test_dashboard_spec(seeded_api: TestClient) -> None:
    meeting_id, result = _analyze_sample(seeded_api)
    response = seeded_api.get(f"/api/meetings/{meeting_id}/dashboard")
    assert response.status_code == 200
    spec = response.json()
    assert spec["version"] == 1
    assert spec["title"] == "Enterprise Revenue Review · dashboard"
    assert spec["periods"] == {"previous": "2026-08-01", "current": "2026-09-01"}
    assert [w["type"] for w in spec["widgets"]] == ["summary", "kpis", "bar_chart", "bar_chart", "bar_chart", "recommendations"]

    summary, kpis, revenue_chart, decline_chart, participation, recs = spec["widgets"]
    assert summary["headline"] == result["summary"]["headline"]
    assert summary["detail"] == result["meeting"]["summary"]
    assert participation["id"] == "participation" and participation["unit"] == "percent"
    assert kpis["kpis"] == result["kpis"] and kpis["previous_label"] == "Aug 2026"

    assert revenue_chart["id"] == "revenue_by_account"
    assert [s["label"] for s in revenue_chart["series"]] == ["Aug 2026", "Sep 2026"]
    assert revenue_chart["data"] == [
        {"account": "Acme", "previous": 820000, "current": 630000},
        {"account": "Gamma", "previous": 610000, "current": 530000},
        {"account": "Beta", "previous": 540000, "current": 420000},
        {"account": "Other", "previous": 420000, "current": 370000},
    ]
    assert sum(row["previous"] for row in revenue_chart["data"]) == 2390000
    assert sum(row["current"] for row in revenue_chart["data"]) == 1950000

    assert decline_chart["orientation"] == "horizontal"
    assert [(row["account"], row["change"]) for row in decline_chart["data"]] == [
        ("Acme", -190000),
        ("Beta", -120000),
        ("Gamma", -80000),
        ("Other", -50000),
    ]
    assert recs["items"] == result["recommendations"]


def test_latest_dashboard_follows_most_recent_analysis(seeded_api: TestClient) -> None:
    assert seeded_api.get("/api/dashboard/latest").status_code == 404
    first_id, _ = _analyze_sample(seeded_api)
    assert seeded_api.get("/api/dashboard/latest").json()["meeting_id"] == first_id
    second_id, _ = _analyze_sample(seeded_api)
    assert seeded_api.get("/api/dashboard/latest").json()["meeting_id"] == second_id
    # Re-analyzing the first meeting makes its dashboard the latest again.
    seeded_api.post(f"/api/meetings/{first_id}/analyze")
    assert seeded_api.get("/api/dashboard/latest").json()["meeting_id"] == first_id


def test_reanalysis_keeps_one_dashboard_per_meeting(seeded_api: TestClient, seeded_db) -> None:
    from sqlalchemy import func, select

    from app.db.models import DashboardSpec

    meeting_id, _ = _analyze_sample(seeded_api)
    seeded_api.post(f"/api/meetings/{meeting_id}/analyze")
    seeded_api.post(f"/api/meetings/{meeting_id}/analyze")
    with seeded_db() as session:
        assert session.scalar(select(func.count()).select_from(DashboardSpec)) == 1


def test_dashboard_not_found_cases(seeded_api: TestClient) -> None:
    assert seeded_api.get(f"/api/meetings/{uuid4()}/dashboard").status_code == 404
    meeting_id = seeded_api.post("/api/meetings/sample").json()["id"]
    response = seeded_api.get(f"/api/meetings/{meeting_id}/dashboard")
    assert (response.status_code, response.json()["detail"]) == (404, "No dashboard yet. Analyze the meeting first.")


def test_meeting_without_business_topics_ignores_business_data(seeded_api: TestClient) -> None:
    meeting = seeded_api.post(
        "/api/meetings",
        json={"title": "Ops", "segments": [{"speaker": "Lead", "text": "We will follow up next week."}]},
    ).json()
    result = seeded_api.post(f"/api/meetings/{meeting['id']}/analyze").json()
    # Business data exists, but this meeting never discussed customers or revenue: none of it is shown.
    assert result["business_context"] is False
    titles = [(r["priority"], r["title"], r["due"]) for r in result["recommendations"]]
    assert titles == [("medium", "We will follow up next week", "next week")]
    spec = seeded_api.get(f"/api/meetings/{meeting['id']}/dashboard").json()
    for name in ("Acme", "Beta", "Gamma", "Revenue"):
        assert name not in str(result) and name not in str(spec)
