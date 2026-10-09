"""Action item tracking: tasks from meetings get a status, a real due date, and survive re-analysis."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.workflows.action_items import today


def _meeting(api: TestClient, lines: list[tuple[str, str]], title: str = "Launch sync") -> str:
    body = {"title": title, "segments": [{"speaker": speaker, "text": text} for speaker, text in lines]}
    meeting_id = api.post("/api/meetings", json=body).json()["id"]
    assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200
    return meeting_id


LINES = [
    ("Ravi", "I will send the proposal by tomorrow."),
    ("Asha", "I will prepare the budget by next week."),
    ("Ravi", "We need to update the price list."),
]


def _tasks(api: TestClient, view: str = "all", **params) -> dict:
    return api.get("/api/action-items", params={"view": view, **params}).json()


def test_tasks_are_created_with_real_due_dates(api: TestClient) -> None:
    _meeting(api, LINES)
    data = _tasks(api)
    tasks = {t["task"]: t for t in data["tasks"]}
    proposal = tasks["I will send the proposal by tomorrow"]
    assert (proposal["owner"], proposal["due_text"], proposal["status"]) == ("Ravi", "tomorrow", "open")
    assert proposal["due_date"] == (today() + timedelta(days=1)).isoformat()
    assert proposal["quote"] == "I will send the proposal by tomorrow." and proposal["index"] is not None
    price = tasks["We need to update the price list"]
    assert price["owner"] is None and price["due_date"] is None
    assert data["counts"] == {"open": 3, "in_progress": 0, "overdue": 0, "due_today": 0, "done": 0, "unassigned": 1}
    assert data["owners"] == ["Asha", "Ravi"]
    # Most urgent first: tomorrow, then next week, undated last.
    assert [t["task"] for t in data["tasks"]][-1] == "We need to update the price list"


def test_status_owner_and_due_date_updates_survive_reanalysis(api: TestClient) -> None:
    meeting_id = _meeting(api, LINES)
    tasks = {t["task"]: t for t in _tasks(api)["tasks"]}
    proposal, price = tasks["I will send the proposal by tomorrow"], tasks["We need to update the price list"]

    assert api.patch(f"/api/action-items/{proposal['id']}", json={"status": "done"}).status_code == 200
    yesterday = (today() - timedelta(days=1)).isoformat()
    api.patch(f"/api/action-items/{price['id']}", json={"owner": "Asha", "due_date": yesterday, "status": "in_progress"})

    data = _tasks(api)
    assert data["counts"]["done"] == 1 and data["counts"]["in_progress"] == 1 and data["counts"]["overdue"] == 1
    assert [t["task"] for t in _tasks(api, "overdue")["tasks"]] == ["We need to update the price list"]
    done = _tasks(api, "done")["tasks"]
    assert [t["task"] for t in done] == ["I will send the proposal by tomorrow"] and done[0]["completed_at"]

    assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200  # re-run analysis
    after = {t["task"]: t for t in _tasks(api)["tasks"]}
    assert after["I will send the proposal by tomorrow"]["status"] == "done"
    kept = after["We need to update the price list"]
    assert (kept["owner"], kept["due_date"], kept["status"], kept["edited"]) == ("Asha", yesterday, "in_progress", True)
    assert len(after) == 3  # no duplicates

    reopened = api.patch(f"/api/action-items/{proposal['id']}", json={"status": "open"}).json()
    assert next(t for t in reopened["tasks"] if t["id"] == proposal["id"])["completed_at"] is None


def test_views_and_owner_filter(api: TestClient) -> None:
    _meeting(api, LINES)
    assert [t["owner"] for t in _tasks(api, "open", owner="Ravi")["tasks"]] == ["Ravi"]
    assert len(_tasks(api, "due_soon")["tasks"]) == 2  # tomorrow and next week; undated is not "due soon"
    assert _tasks(api, "done")["tasks"] == []


def test_validation(api: TestClient) -> None:
    _meeting(api, LINES)
    task_id = _tasks(api)["tasks"][0]["id"]
    assert api.patch(f"/api/action-items/{task_id}", json={"status": "finished"}).status_code == 422
    assert api.patch("/api/action-items/99999", json={"status": "done"}).status_code == 404
    assert api.get("/api/action-items", params={"view": "someday"}).status_code == 422


def test_removed_items_and_deleted_meetings_drop_their_tasks(api: TestClient) -> None:
    meeting_id = _meeting(api, LINES)
    task = next(t for t in _tasks(api)["tasks"] if t["task"] == "We need to update the price list")
    removed = api.delete(f"/api/meetings/{meeting_id}/items/action_items/{task['index']}", params={"text": task["task"]})
    assert removed.status_code == 204
    assert "We need to update the price list" not in [t["task"] for t in _tasks(api)["tasks"]]

    assert api.delete(f"/api/meetings/{meeting_id}").status_code == 204
    assert _tasks(api)["tasks"] == []


def test_meetings_analyzed_before_tracking_get_their_tasks(api: TestClient, memory_db) -> None:
    from app.db.models import ActionItem

    _meeting(api, LINES)
    with memory_db() as db:  # as if the meeting had been analyzed before this feature existed
        db.execute(delete(ActionItem))
        db.commit()
    assert len(_tasks(api)["tasks"]) == 3


def _reworded(segments, known_customers):
    """A mock LLM run that phrases the same tasks a little differently, as real models do on a re-run."""
    from app.plugins.llm import MockLLMProvider

    result = MockLLMProvider().extract_signals(segments, known_customers)
    for item in result.meeting.action_items:
        item.task = item.task.replace("I will send the proposal", "Send the proposal to the client").replace("I will prepare", "Prepare")
    return result


def test_reworded_tasks_keep_their_status_on_reanalysis(api: TestClient) -> None:
    from app.main import app
    from app.plugins.llm import get_llm_provider

    meeting_id = _meeting(api, LINES)
    proposal = next(t for t in _tasks(api)["tasks"] if t["task"].startswith("I will send the proposal"))
    api.patch(f"/api/action-items/{proposal['id']}", json={"status": "done"})

    class Reworded:
        name = "mock"
        extract_signals = staticmethod(_reworded)

    app.dependency_overrides[get_llm_provider] = lambda: Reworded()
    try:
        assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200
    finally:
        del app.dependency_overrides[get_llm_provider]
    after = {t["id"]: t for t in _tasks(api)["tasks"]}
    assert proposal["id"] in after, "the finished task was deleted and recreated"
    assert after[proposal["id"]]["status"] == "done"
    assert after[proposal["id"]]["task"] == "Send the proposal to the client by tomorrow"  # new wording is taken over
    assert len(after) == 3


def test_manual_due_date_replaces_the_spoken_wording(api: TestClient) -> None:
    _meeting(api, LINES)
    task = next(t for t in _tasks(api)["tasks"] if t["due_text"] == "tomorrow")
    updated = next(t for t in api.patch(f"/api/action-items/{task['id']}", json={"due_date": "2026-12-01"}).json()["tasks"] if t["id"] == task["id"])
    assert (updated["due_date"], updated["due_text"]) == ("2026-12-01", None)
