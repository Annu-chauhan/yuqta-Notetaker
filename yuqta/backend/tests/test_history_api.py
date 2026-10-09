"""Meeting history: action items, decisions, risks and questions across all meetings."""

from fastapi.testclient import TestClient


def _meeting(api: TestClient, title: str, lines: list[tuple[str, str]]) -> str:
    body = {"title": title, "segments": [{"speaker": speaker, "text": text} for speaker, text in lines]}
    meeting_id = api.post("/api/meetings", json=body).json()["id"]
    assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200
    return meeting_id


def test_history_collects_items_across_meetings(api: TestClient) -> None:
    first = _meeting(api, "Website sync", [
        ("Asha", "We agreed to go live on the first of December."),
        ("Ravi", "I will finish the product pages by next Wednesday."),
        ("Asha", "My concern is the hosting cost."),
    ])
    second = _meeting(api, "Sales sync", [
        ("Ravi", "I will send the proposal by Friday."),
        ("Asha", "We need to update the price list."),
        ("Ravi", "Who will call the new client?"),
    ])
    api.post("/api/meetings", json={"title": "Not analyzed", "segments": [{"speaker": "X", "text": "Hello"}]})

    history = api.get("/api/history").json()
    assert history["totals"] == {
        "meetings": 3, "analyzed": 2, "action_items": 3, "unassigned_action_items": 1,
        "decisions": 1, "risks": 1, "open_questions": 1,
    }
    # Newest first in Postgres; SQLite timestamps tie within a second, so only the set is checked here.
    meetings = {m["title"]: m for m in history["meetings"]}
    assert set(meetings) == {"Not analyzed", "Sales sync", "Website sync"}
    assert meetings["Not analyzed"]["headline"] is None and meetings["Not analyzed"]["action_items"] == 0
    assert meetings["Website sync"]["headline"] and meetings["Website sync"]["decisions"] == 1

    tasks = {(a["text"], a["owner"], a["due"], a["meeting_id"]) for a in history["action_items"]}
    assert ("I will finish the product pages by next Wednesday", "Ravi", "by next wednesday", first) in tasks
    assert ("I will send the proposal by Friday", "Ravi", "by friday", second) in tasks
    assert history["owners"] == [{"owner": "Ravi", "action_items": 2}, {"owner": "Unassigned", "action_items": 1}]
    assert history["decisions"][0]["meeting_title"] == "Website sync"
    assert history["open_questions"][0]["quote"] == "Who will call the new client?"


def test_history_is_empty_without_meetings(api: TestClient) -> None:
    history = api.get("/api/history").json()
    assert history["totals"]["meetings"] == 0 and history["action_items"] == [] and history["owners"] == []


def test_deleting_a_meeting_removes_everything_it_produced(api: TestClient, memory_db) -> None:
    from app.db.models import DashboardSpec, MeetingBot, MeetingInsight, TranscriptSegment

    keep = _meeting(api, "Keep me", [("Asha", "We agreed to launch in December.")])
    gone = _meeting(api, "Delete me", [("Ravi", "I will send the proposal by Friday.")])
    with memory_db() as db:
        db.add(MeetingBot(provider="recall", external_id="b1", meeting_url="https://meet.google.com/abc-defg-hij",
                          title="Delete me", status="analyzed", detail="done", meeting_id=__import__("uuid").UUID(gone)))
        db.commit()

    assert api.delete(f"/api/meetings/{gone}").status_code == 204
    assert api.get(f"/api/meetings/{gone}").status_code == 404
    assert api.delete(f"/api/meetings/{gone}").status_code == 404
    history = api.get("/api/history").json()
    assert [m["title"] for m in history["meetings"]] == ["Keep me"] and history["action_items"] == []

    with memory_db() as db:
        for model in (TranscriptSegment, MeetingInsight, DashboardSpec):
            assert {str(row.meeting_id) for row in db.query(model)} == {keep}
        bot = db.query(MeetingBot).one()
        assert bot.meeting_id is None and bot.detail == "The meeting was deleted."


def test_removing_one_item_updates_analysis_dashboard_and_history(api: TestClient) -> None:
    meeting_id = _meeting(api, "Website sync", [
        ("Asha", "We agreed to go live on the first of December."),
        ("Ravi", "I will finish the product pages by next Wednesday."),
        ("Ravi", "I will email the agency today."),
        ("Asha", "My concern is the hosting cost."),
        ("Ravi", "Who will write the About page?"),
    ])

    def remove(kind: str, index: int, text: str):
        return api.delete(f"/api/meetings/{meeting_id}/items/{kind}/{index}", params={"text": text})

    history = api.get("/api/history").json()
    task = next(a for a in history["action_items"] if a["text"] == "I will email the agency today")
    assert (task["kind"], task["index"]) == ("action_items", 1)
    assert remove("action_items", 1, "Wrong text").status_code == 409  # stale page: nothing removed
    assert remove("action_items", 1, task["text"]).status_code == 204
    assert remove("risks", 0, "My concern is the hosting cost.").status_code == 204
    assert remove("open_questions", 0, "Who will write the About page?").status_code == 204
    assert remove("open_questions", 0, "Who will write the About page?").status_code == 409  # already gone

    analysis = api.get(f"/api/meetings/{meeting_id}/analysis").json()
    assert [a["task"] for a in analysis["meeting"]["action_items"]] == ["I will finish the product pages by next Wednesday"]
    assert analysis["meeting"]["risks"] == [] and analysis["meeting"]["open_questions"] == []
    assert [r["title"] for r in analysis["recommendations"]] == ["I will finish the product pages by next Wednesday"]

    spec = api.get(f"/api/meetings/{meeting_id}/dashboard").json()
    widgets = {w.get("id", w["type"]): w for w in spec["widgets"]}
    assert "risks" not in widgets and "open_questions" not in widgets and "decisions" in widgets
    glance = {k["key"]: k["value"] for k in widgets["kpis"]["kpis"]}
    assert (glance["action_items"], glance["risks"], glance["open_questions"], glance["decisions"]) == (1, 0, 0, 1)
    assert [r["title"] for r in widgets["recommendations"]["items"]] == ["I will finish the product pages by next Wednesday"]
    assert api.get("/api/history").json()["totals"]["action_items"] == 1

    assert api.delete(f"/api/meetings/{meeting_id}/items/topics/0", params={"text": "x"}).status_code == 422
