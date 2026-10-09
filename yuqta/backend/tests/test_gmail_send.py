"""Email through the connected (registered) Google account: no SMTP or app password needed."""

from base64 import urlsafe_b64decode
from email import message_from_bytes, policy
from urllib.parse import urlparse
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

import app.connectors.google as google_module
from app.connectors.google import GoogleConnector
from app.connectors.google.client import GMAIL_SEND_SCOPE
from app.connectors.google.mock import MockGoogleWorkspaceClient
from app.core.config import Settings, get_settings
from app.core.mailer import mail_configured, registered_emails
from app.db.models import MeetingBot
from app.workflows.minutes import admin_recipients, after_analysis
from app.workflows.reminders import configured as reminders_configured

REGISTERED = "demo.user@example.com"  # the mock Google account


def _settings(**overrides) -> Settings:
    base = dict(_env_file=None, gmail_send=True, minutes_email="review", internal_domains="iqlytics.in",
                frontend_url="http://yuqta.test", google_redirect_uri="http://backend.test/auth/google/callback",
                sample_transcript_path=get_settings().sample_transcript_path)
    return Settings(**{**base, **overrides})


@pytest.fixture
def google(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> GoogleConnector:
    """A connected mock Google account that allowed sending email, used by the mailer."""
    settings = _settings()
    connector = GoogleConnector(client=MockGoogleWorkspaceClient(settings), mode="mock", frontend_url="http://yuqta.test")
    url = connector.start_connect("/import")
    query = dict(pair.split("=", 1) for pair in urlparse(url).query.split("&"))
    connector.complete_connect(query["code"], query["state"], None)
    monkeypatch.setattr(google_module, "get_google_connector", lambda: connector)
    return connector


def _sent(connector: GoogleConnector) -> list:
    return [message_from_bytes(urlsafe_b64decode(raw), policy=policy.default) for raw in connector.client.fake.sent_mail]


def _bot_meeting(api: TestClient, memory_db, **bot) -> UUID:
    body = {"title": "Launch sync", "segments": [{"speaker": "Asha", "text": "We agreed to launch on the first of December."},
                                                 {"speaker": "Ravi", "text": "I will send the proposal by tomorrow."}]}
    meeting_id = api.post("/api/meetings", json=body).json()["id"]
    assert api.post(f"/api/meetings/{meeting_id}/analyze").status_code == 200
    with memory_db() as db:
        db.add(MeetingBot(provider="mock", external_id=f"b-{meeting_id}", meeting_url="https://meet.google.com/abc-defg-hij",
                          title="Launch sync", status="analyzed", detail="", meeting_id=UUID(meeting_id), **bot))
        db.commit()
    return UUID(meeting_id)


def test_registered_account_gets_recording_and_summary_through_gmail(api, memory_db, google) -> None:
    settings = _settings()
    assert mail_configured(settings) and registered_emails(settings) == [REGISTERED]
    meeting_id = _bot_meeting(api, memory_db)
    with memory_db() as db:
        row = after_analysis(db, settings, meeting_id, recording_url=lambda: "https://storage.example/v.mp4")
        assert row.admin_email == REGISTERED and row.admin_sent_at is not None
    [message] = _sent(google)
    assert message["To"] == REGISTERED and message["From"] == f"Yuqta <{REGISTERED}>"
    assert message["Subject"].startswith("Recording and minutes: Launch sync")
    html = message.get_body(("html",)).get_content()
    assert "https://storage.example/v.mp4" in html and "We agreed to launch on the first of December" in html


def test_registered_account_plus_internal_organizer_but_not_an_outside_one(api, memory_db, google) -> None:
    settings = _settings()
    internal = _bot_meeting(api, memory_db, admin_email="host@iqlytics.in")
    outside = _bot_meeting(api, memory_db, admin_email="host@customer.com")
    other_calendar = _bot_meeting(api, memory_db, account_email="annu@gmail.com")
    with memory_db() as db:
        assert admin_recipients(db, settings, internal) == [REGISTERED, "host@iqlytics.in"]
        assert admin_recipients(db, settings, outside) == [REGISTERED]  # the recording never goes outside automatically
        assert admin_recipients(db, settings, other_calendar) == ["annu@gmail.com"]  # whose calendar the meeting was on


def test_gmail_off_or_permission_missing_means_not_set_up(api, google) -> None:
    assert not mail_configured(_settings(gmail_send=False))
    connection = google._connection
    connection.tokens["scope"] = connection.tokens["scope"].replace(GMAIL_SEND_SCOPE, "")  # connected before the permission existed
    assert google.mail_sender() is None and not mail_configured(_settings())


def test_reminders_go_to_the_registered_account_by_default(api, google) -> None:
    assert reminders_configured(_settings())  # no SMTP, no REMINDER_TO: Gmail + the registered account
    assert not reminders_configured(_settings(gmail_send=False))


def test_connect_asks_for_send_permission_only_when_enabled() -> None:
    assert GMAIL_SEND_SCOPE in MockGoogleWorkspaceClient(_settings()).scopes()
    assert GMAIL_SEND_SCOPE not in MockGoogleWorkspaceClient(_settings(gmail_send=False)).scopes()
