"""Calendar auto-join: Meet events on the calendar become scheduled bots, kept in sync with the calendar."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.connectors.google import ConnectorError, get_google_connector
from app.connectors.meeting_bot import get_meeting_bot_client
from app.connectors.meeting_bot.mock import MockMeetingBotClient
from app.core.config import Settings, get_settings
from app.db.models import MeetingBot
from app.db.session import get_session_factory
from app.main import app
from app.workflows import calendar_auto_join
from app.workflows.calendar_auto_join import CalendarAutoJoiner


NOW = datetime.now(timezone.utc).replace(microsecond=0)


class FakeCalendar:
    mode = "mock"

    def __init__(self, events: list[dict], connected: bool = True):
        self.items, self.connected, self.fail = events, connected, False

    def events(self, days_back: int, days_ahead: int) -> list[dict]:
        if self.fail:
            raise ConnectorError("Google API: quota exceeded", 429)
        return self.items


def event(event_id: str, start: timedelta, minutes: int = 30, **extra) -> dict:
    begin = NOW + start
    return {
        "id": event_id, "title": f"Meeting {event_id}", "all_day": False, "declined": False,
        "start": begin.isoformat(), "end": (begin + timedelta(minutes=minutes)).isoformat(),
        "meet_link": "https://meet.google.com/abc-defg-hij", **extra,
    }


@pytest.fixture
def client() -> MockMeetingBotClient:
    return MockMeetingBotClient(get_settings().sample_transcript_path)


def _run(joiner, calendar, client, db_factory, now=NOW):
    return joiner.run_once(calendar, client, db_factory, "Yuqta Notetaker", 24, now=now)


def _bots(db_factory) -> dict[str, MeetingBot]:
    with db_factory() as db:
        rows = db.query(MeetingBot).order_by(MeetingBot.created_at).all()
    return {f"{bot.calendar_event_id}:{bot.status}": bot for bot in rows}


def test_meet_events_get_one_bot_each(memory_db, client) -> None:
    calendar = FakeCalendar([
        event("later", timedelta(hours=2)),
        event("running", timedelta(minutes=-5)),
        event("all-day", timedelta(hours=3), all_day=True),
        event("declined", timedelta(hours=4), declined=True),
        event("no-link", timedelta(hours=5), meet_link=None),
        event("over", timedelta(hours=-2)),
        event("far", timedelta(hours=30)),
    ])
    joiner = CalendarAutoJoiner()
    changes = _run(joiner, calendar, client, memory_db)
    assert len(changes) == 2 and "joining now" in " ".join(changes)

    bots = _bots(memory_db)
    assert set(bots) == {"later:scheduled", "running:joining"}
    later = bots["later:scheduled"]
    assert later.title == "Meeting later" and later.meeting_url == "https://meet.google.com/abc-defg-hij"
    assert later.join_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=2) - timedelta(minutes=1)
    assert "Scheduled: joins at" in later.detail

    assert _run(joiner, calendar, client, memory_db) == []  # running again changes nothing
    assert len(_bots(memory_db)) == 2


def test_moved_and_deleted_events_update_their_bots(memory_db, client) -> None:
    calendar = FakeCalendar([event("moved", timedelta(hours=2)), event("deleted", timedelta(hours=3))])
    joiner = CalendarAutoJoiner()
    _run(joiner, calendar, client, memory_db)

    calendar.items = [event("moved", timedelta(hours=4))]
    changes = _run(joiner, calendar, client, memory_db)
    assert any(c.startswith("Rescheduled") for c in changes) and any(c.startswith("Cancelled") for c in changes)

    bots = _bots(memory_db)
    assert bots["moved:scheduled"].join_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=4, minutes=-1)
    assert bots["moved:cancelled"].detail.startswith("Rescheduled")
    assert bots["deleted:cancelled"].detail.startswith("Cancelled")


def test_bots_about_to_join_are_left_alone(memory_db, client) -> None:
    calendar = FakeCalendar([event("soon", timedelta(minutes=8))])
    joiner = CalendarAutoJoiner()
    _run(joiner, calendar, client, memory_db)
    calendar.items = []  # event deleted 8 minutes before start: too late to cancel safely
    assert _run(joiner, calendar, client, memory_db) == []
    assert "soon:scheduled" in _bots(memory_db)


def test_disconnected_or_failing_calendar_is_reported(memory_db, client) -> None:
    joiner = CalendarAutoJoiner()
    assert _run(joiner, FakeCalendar([], connected=False), client, memory_db) == []
    assert joiner.last_error == "Google Calendar is not connected."
    failing = FakeCalendar([])
    failing.fail = True
    _run(joiner, failing, client, memory_db)
    assert "quota exceeded" in joiner.last_error


def test_api_sync_and_cancel(seeded_api: TestClient, seeded_db, client, monkeypatch: pytest.MonkeyPatch) -> None:
    calendar = FakeCalendar([event("standup", timedelta(hours=1))])
    settings = Settings(_env_file=None, auto_join_calendar=True, sample_transcript_path=get_settings().sample_transcript_path)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_google_connector] = lambda: calendar
    app.dependency_overrides[get_meeting_bot_client] = lambda: client
    app.dependency_overrides[get_session_factory] = lambda: seeded_db
    joiner = CalendarAutoJoiner()
    monkeypatch.setattr(calendar_auto_join, "calendar_auto_joiner", joiner)
    import app.api.bots as bots_api

    monkeypatch.setattr(bots_api, "calendar_auto_joiner", joiner)

    status = seeded_api.post("/api/bots/calendar/sync").json()
    assert status["enabled"] and status["google_connected"] and "Scheduled bot for" in status["recent"][0]
    bot = seeded_api.get("/api/bots").json()["bots"][0]
    assert bot["status"] == "scheduled" and bot["calendar_event_id"] == "standup" and bot["join_at"]
    assert seeded_api.post("/api/bots/check").json()["bots"][0]["status"] == "scheduled"  # poller waits for join time

    cancelled = seeded_api.post(f"/api/bots/{bot['id']}/leave").json()
    assert cancelled["status"] == "cancelled" and cancelled["detail"] == "Cancelled before the meeting."
    seeded_api.post("/api/bots/calendar/sync")  # a bot the user cancelled is not re-created
    assert [b["status"] for b in seeded_api.get("/api/bots").json()["bots"]] == ["cancelled"]


def test_sync_refuses_when_turned_off(seeded_api: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, auto_join_calendar=False)
    response = seeded_api.post("/api/bots/calendar/sync")
    assert response.status_code == 409 and "AUTO_JOIN_CALENDAR" in response.json()["detail"]



def test_network_problems_are_reported_as_temporary(memory_db, client) -> None:
    class Offline(FakeCalendar):
        def events(self, days_back, days_ahead):
            raise ConnectorError("Google API: Could not reach Google: [Errno -2] Name or service not known", 502)

    joiner = CalendarAutoJoiner()
    _run(joiner, Offline([]), client, memory_db)
    assert joiner.last_error == "Could not reach Google (network problem). Yuqta retries automatically on the next check."
    _run(joiner, FakeCalendar([]), client, memory_db)
    assert joiner.last_error is None  # cleared as soon as Google is reachable again
