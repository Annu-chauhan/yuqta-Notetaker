"""Daily task reminder email: content, once-a-day sending, and the API."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings, get_settings
from app.main import app
from app.core import mailer
from app.workflows import reminders
from app.workflows.action_items import today
from app.workflows.reminders import ReminderScheduler, build_digest


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if password != "app-password":
            import smtplib

            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, message):
        FakeSMTP.sent.append(message)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _settings(**overrides) -> Settings:
    base = dict(_env_file=None, smtp_host="smtp.example.com", smtp_user="me@example.com", smtp_password="app-password",
                smtp_from="Yuqta <me@example.com>", reminder_to="team@example.com, boss@example.com", reminder_hour=9,
                frontend_url="http://yuqta.test")
    return Settings(**{**base, **overrides})


def _tasks_with_dates(api: TestClient) -> None:
    body = {"title": "Ops sync", "segments": [
        {"speaker": "Ravi", "text": "I will send the proposal by tomorrow."},
        {"speaker": "Asha", "text": "I will update the price list today."},
        {"speaker": "Asha", "text": "We need to fix the login page."},
    ]}
    meeting_id = api.post("/api/meetings", json=body).json()["id"]
    api.post(f"/api/meetings/{meeting_id}/analyze")
    tasks = api.get("/api/action-items", params={"view": "all"}).json()["tasks"]
    login = next(t for t in tasks if "login" in t["task"])
    api.patch(f"/api/action-items/{login['id']}", json={"due_date": (today() - timedelta(days=2)).isoformat()})


def test_digest_groups_by_owner_and_flags_overdue(api: TestClient, memory_db) -> None:
    _tasks_with_dates(api)
    with memory_db() as db:
        digest = build_digest(db, "http://yuqta.test")
    assert (digest.overdue, digest.due_today, digest.due_soon) == (1, 1, 1)
    assert "1 overdue, 1 due today, 1 due in the next 3 days" in digest.subject
    assert "Asha:" in digest.text and "Ravi:" in digest.text and "OVERDUE by 2 days" in digest.text
    assert "due TODAY" in digest.text and "http://yuqta.test/history" in digest.text
    assert "<li>" in digest.html


def test_sent_once_a_day_after_the_hour(api: TestClient, memory_db, smtp) -> None:
    _tasks_with_dates(api)
    scheduler = ReminderScheduler()
    morning = datetime.now(timezone.utc).replace(hour=7, minute=0)
    assert scheduler.run_once(_settings(), memory_db, now=morning) is False  # before 09:00
    later = morning.replace(hour=10)
    assert scheduler.run_once(_settings(), memory_db, now=later) is True
    assert scheduler.run_once(_settings(), memory_db, now=later + timedelta(hours=2)) is False  # already sent today
    [message] = smtp.sent
    assert message["To"] == "team@example.com, boss@example.com" and "overdue" in message["Subject"]


def test_failed_login_is_reported_and_retried(api: TestClient, memory_db, smtp) -> None:
    _tasks_with_dates(api)
    scheduler = ReminderScheduler()
    at_ten = datetime.now(timezone.utc).replace(hour=10)
    assert scheduler.run_once(_settings(smtp_password="wrong"), memory_db, now=at_ten) is False
    assert "app password" in scheduler.last_error
    assert scheduler.run_once(_settings(), memory_db, now=at_ten) is True  # fixed: sent on the next run


def test_nothing_due_sends_nothing(api: TestClient, memory_db, smtp) -> None:
    assert ReminderScheduler().run_once(_settings(), memory_db, now=datetime.now(timezone.utc).replace(hour=10)) is False
    assert smtp.sent == []


def test_api_status_and_send_now(api: TestClient, smtp) -> None:
    _tasks_with_dates(api)
    assert api.get("/api/action-items/reminders").json()["configured"] is False
    assert api.post("/api/action-items/reminders/send").status_code == 409  # not set up
    app.dependency_overrides[get_settings] = lambda: _settings()
    try:
        status = api.get("/api/action-items/reminders").json()
        assert status["configured"] and status["recipients"] == ["team@example.com", "boss@example.com"]
        assert status["preview"]["overdue"] == 1
        sent = api.post("/api/action-items/reminders/send").json()
        assert sent["sent_to"] == ["team@example.com", "boss@example.com"] and len(smtp.sent) == 1
    finally:
        app.dependency_overrides.pop(get_settings, None)
