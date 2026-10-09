"""Meeting minutes email: built from the analysis, sent once, held for approval when it leaves the organisation."""

from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app.connectors.google.client import simplify_event
from app.core import mailer
from app.core.config import Settings, get_settings
from app.db.models import MeetingBot, MinutesEmail
from app.main import app
from app.workflows.minutes import after_analysis

from tests.test_reminders import FakeSMTP


LINES = [
    ("Asha", "We agreed to launch on the first of December."),
    ("Ravi", "I will send the proposal by tomorrow."),
    ("Asha", "My concern is the <hosting> cost."),
    ("Ravi", "Who will write the About page?"),
]


def _settings(**overrides) -> Settings:
    base = dict(_env_file=None, smtp_host="smtp.example.com", smtp_user="me@iqlytics.in", smtp_password="app-password",
                smtp_from="Yuqta <me@iqlytics.in>", minutes_email="auto", internal_domains="iqlytics.in",
                frontend_url="http://yuqta.test", sample_transcript_path=get_settings().sample_transcript_path)
    return Settings(**{**base, **overrides})


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def settings_override():
    def use(settings: Settings) -> Settings:
        app.dependency_overrides[get_settings] = lambda: settings
        return settings

    yield use
    app.dependency_overrides.pop(get_settings, None)


def _bot_meeting(api: TestClient, memory_db, attendees: list[str]) -> UUID:
    body = {"title": "Launch sync", "segments": [{"speaker": s, "text": t} for s, t in LINES]}
    meeting_id = api.post("/api/meetings", json=body).json()["id"]
    assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200
    with memory_db() as db:
        db.add(MeetingBot(provider="mock", external_id=f"b-{meeting_id}", meeting_url="https://meet.google.com/abc-defg-hij",
                          title="Launch sync", status="analyzed", detail="", meeting_id=UUID(meeting_id), attendee_emails=attendees))
        db.commit()
    return UUID(meeting_id)


def test_internal_meeting_is_sent_once_with_the_minutes(api, memory_db, smtp) -> None:
    meeting_id = _bot_meeting(api, memory_db, ["Asha@iqlytics.in", "ravi@iqlytics.in"])
    settings = _settings()
    with memory_db() as db:
        row = after_analysis(db, settings, meeting_id)
        assert (row.status, row.recipients) == ("sent", ["asha@iqlytics.in", "ravi@iqlytics.in"])
    [message] = smtp.sent
    assert message["Subject"].startswith("Minutes: Launch sync")
    html = message.get_body(("html",)).get_content()
    text = message.get_body(("plain",)).get_content()
    assert "We agreed to launch on the first of December" in text
    assert "I will send the proposal by tomorrow" in text and "Ravi" in text  # task with owner and real date
    assert "&lt;hosting&gt;" in html and "<hosting>" not in html  # transcript text is escaped
    assert f"http://yuqta.test/meetings/{meeting_id}" in text

    with memory_db() as db:  # re-analysis must not send again
        after_analysis(db, settings, meeting_id)
    assert len(smtp.sent) == 1


def test_external_recipients_wait_for_approval(api, memory_db, smtp, settings_override) -> None:
    meeting_id = _bot_meeting(api, memory_db, ["asha@iqlytics.in", "client@customer.com"])
    settings = settings_override(_settings())
    with memory_db() as db:
        row = after_analysis(db, settings, meeting_id)
        assert row.status == "awaiting_approval" and "client@customer.com" in row.detail
    assert smtp.sent == []

    status = api.get(f"/api/meetings/{meeting_id}/minutes").json()
    assert status["status"] == "awaiting_approval" and status["external"] == ["client@customer.com"]
    assert "Launch sync" in status["preview_html"]

    sent = api.post(f"/api/meetings/{meeting_id}/minutes/send", json={"recipients": ["asha@iqlytics.in"]}).json()
    assert (sent["status"], sent["recipients"], sent["external"]) == ("sent", ["asha@iqlytics.in"], [])
    assert smtp.sent[0]["To"] == "asha@iqlytics.in"


def test_review_mode_holds_and_off_mode_does_nothing(api, memory_db, smtp) -> None:
    meeting_id = _bot_meeting(api, memory_db, ["asha@iqlytics.in"])
    with memory_db() as db:
        assert after_analysis(db, _settings(minutes_email="off"), meeting_id) is None
        assert db.get(MinutesEmail, meeting_id) is None
        assert after_analysis(db, _settings(minutes_email="review"), meeting_id).status == "awaiting_approval"
        assert after_analysis(db, _settings(smtp_host=""), meeting_id) is None  # email not set up: nothing happens
        assert db.get(MinutesEmail, meeting_id).status == "awaiting_approval"
    assert smtp.sent == []


def test_minutes_to_is_trusted_and_no_recipients_is_skipped(api, memory_db, smtp) -> None:
    first = _bot_meeting(api, memory_db, [])
    with memory_db() as db:
        assert after_analysis(db, _settings(), first).status == "skipped"
    second = _bot_meeting(api, memory_db, [])
    with memory_db() as db:
        row = after_analysis(db, _settings(minutes_to="team@gmail.com", internal_domains=""), second)
        assert (row.status, row.recipients) == ("sent", ["team@gmail.com"])  # MINUTES_TO counts as internal


def test_send_errors(api, memory_db, smtp, settings_override) -> None:
    meeting_id = _bot_meeting(api, memory_db, [])
    settings_override(_settings())
    response = api.post(f"/api/meetings/{meeting_id}/minutes/send", json={"recipients": ["not-an-address"]})
    assert (response.status_code, response.json()["detail"]) == (422, "Add at least one valid email address.")

    settings_override(_settings(smtp_password="wrong"))
    response = api.post(f"/api/meetings/{meeting_id}/minutes/send", json={"recipients": ["asha@iqlytics.in"]})
    assert response.status_code == 502 and "app password" in response.json()["detail"]
    assert api.get(f"/api/meetings/{meeting_id}/minutes").json()["status"] == "failed"

    settings_override(_settings(smtp_host=""))
    other = _bot_meeting(api, memory_db, [])
    assert api.post(f"/api/meetings/{other}/minutes/send", json={"recipients": ["a@iqlytics.in"]}).status_code == 409
    assert api.get(f"/api/meetings/{other}/minutes").json()["status"] == "not_sent"  # not recorded as failed

    unanalyzed = api.post("/api/meetings", json={"title": "x", "segments": [{"speaker": "A", "text": "Hi"}]}).json()["id"]
    settings_override(_settings())
    assert api.get(f"/api/meetings/{unanalyzed}/minutes").json()["preview_html"] is None
    assert api.post(f"/api/meetings/{unanalyzed}/minutes/send", json={"recipients": ["a@iqlytics.in"]}).status_code == 409


def test_calendar_attendee_emails() -> None:
    event = simplify_event({"id": "e", "summary": "Sync", "start": {"dateTime": "2026-10-09T10:00:00Z"}, "attendees": [
        {"email": "asha@iqlytics.in", "responseStatus": "accepted"},
        {"email": "ravi@iqlytics.in", "responseStatus": "declined"},
        {"email": "room-1@resource.calendar.google.com", "resource": True},
        {"displayName": "No address"},
    ]})
    assert event["attendee_emails"] == ["asha@iqlytics.in"]
