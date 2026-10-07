"""Auto-import of finished Meet meetings, end to end against the mock Google API (+ fake Pub/Sub)."""

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlparse
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app.connectors.google import ConnectorError, GoogleConnector, get_google_connector
from app.connectors.google.client import TRANSCRIPT_READY, GoogleWorkspaceClient
from app.connectors.google.mock import MOCK_ACCOUNT_ID, MockGoogleWorkspaceClient
from app.core.config import Settings, get_settings
from app.db.models import Meeting
from app.db.session import get_session_factory
from app.main import app
from app.plugins.llm import LLMError, MockLLMProvider
from app.workflows import auto_import
from app.workflows.auto_import import AutoImporter


def _settings(**overrides) -> Settings:
    base = dict(_env_file=None, google_redirect_uri="http://backend.test/auth/google/callback", frontend_url="http://frontend.test",
                sample_transcript_path=get_settings().sample_transcript_path)
    return Settings(**{**base, **overrides})


@pytest.fixture
def connector() -> GoogleConnector:
    settings = _settings()
    return GoogleConnector(client=MockGoogleWorkspaceClient(settings), mode="mock", frontend_url=settings.frontend_url)


@pytest.fixture
def google(seeded_api: TestClient, seeded_db, connector: GoogleConnector, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app.dependency_overrides[get_google_connector] = lambda: connector
    app.dependency_overrides[get_session_factory] = lambda: seeded_db
    monkeypatch.setattr(auto_import, "auto_importer", AutoImporter())
    import app.api.google as google_api

    monkeypatch.setattr(google_api, "auto_importer", auto_import.auto_importer)
    return seeded_api


def _connect(client: TestClient) -> None:
    url = client.post("/api/google/connect", json={}).json()["authorization_url"]
    assert client.get(f"/auth/google/callback?{urlparse(url).query}", follow_redirects=False).status_code == 302


def _message(transcript: str, event_type: str = TRANSCRIPT_READY) -> dict:
    data = b64encode(json.dumps({"transcript": {"name": transcript}}).encode()).decode()
    return {"ackId": f"ack-{transcript}-{len(transcript)}", "message": {"data": data, "attributes": {"ce-type": event_type}}}


def test_connect_creates_events_subscription(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    status = google.get("/api/google/auto-import").json()
    assert status["configured"] is True and status["connected"] is True and status["error"] is None
    assert status["events_subscription"] == "subscriptions/mock-1"
    sub = connector.client.fake._subscriptions["subscriptions/mock-1"]
    assert sub["targetResource"] == f"//cloudidentity.googleapis.com/users/{MOCK_ACCOUNT_ID}"
    assert sub["eventTypes"] == [TRANSCRIPT_READY]
    assert sub["notificationEndpoint"]["pubsubTopic"] == "projects/yuqta-mock/topics/meet-events"


def test_reconnect_reuses_existing_subscription(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    google.post("/api/google/disconnect")
    _connect(google)
    assert list(connector.client.fake._subscriptions) == ["subscriptions/mock-1"]


def test_finished_meeting_is_imported_and_analyzed(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    status = google.post("/api/google/auto-import/simulate").json()
    [entry] = status["recent"]
    assert entry["status"] == "analyzed" and entry["title"] == "Enterprise Revenue Review"
    assert entry["transcript"] == "conferenceRecords/sim-1/transcripts/t1"
    assert connector.client.fake._queue == []  # acknowledged

    meeting = google.get(f"/api/meetings/{entry['meeting_id']}").json()
    assert (meeting["source"], meeting["status"], meeting["segment_count"]) == ("google_meet", "analyzed", 4)
    assert meeting["participants"] == ["Sales Manager", "Finance Manager", "Product Manager"]  # from the Calendar event
    dashboard = google.get("/api/dashboard/latest").json()
    assert dashboard["meeting_id"] == entry["meeting_id"]


def test_redelivered_event_is_not_imported_twice(google: TestClient, connector: GoogleConnector, seeded_db) -> None:
    _connect(google)
    google.post("/api/google/auto-import/simulate")
    connector.client.fake._queue.append(_message("conferenceRecords/sim-1/transcripts/t1"))  # Pub/Sub redelivery
    status = google.post("/api/google/auto-import/run").json()
    assert status["recent"][0]["status"] == "duplicate"
    with seeded_db() as db:
        assert db.query(Meeting).filter(Meeting.external_ref == "conferenceRecords/sim-1/transcripts/t1").count() == 1
    assert connector.client.fake._queue == []


def test_transient_failure_is_retried(connector: GoogleConnector, seeded_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    importer = AutoImporter()
    url = connector.start_connect("/import")
    state = urlparse(url).query.split("state=")[1]
    connector.complete_connect("mock-code", state, None)
    connector.client.fake.simulate_transcript_ready()

    original = connector.transcript_segments
    monkeypatch.setattr(connector, "transcript_segments", lambda name: (_ for _ in ()).throw(ConnectorError("Google API: backend error", 502)))
    [failed] = importer.run_once(connector, seeded_db, MockLLMProvider)
    assert failed.status == "failed"
    assert len(connector.client.fake._queue) == 1  # not acknowledged -> Pub/Sub will redeliver

    monkeypatch.setattr(connector, "transcript_segments", original)
    [ok] = importer.run_once(connector, seeded_db, MockLLMProvider)
    assert ok.status == "analyzed" and connector.client.fake._queue == []
    assert settings.auto_import_configured is False  # real settings unchanged; mock supplies a fake topic


def test_analysis_failure_keeps_the_import(connector: GoogleConnector, seeded_db) -> None:
    state = urlparse(connector.start_connect("/import")).query.split("state=")[1]
    connector.complete_connect("mock-code", state, None)
    connector.client.fake.simulate_transcript_ready()

    def broken_llm():
        raise LLMError("OpenRouter rate limit reached; try again shortly.")

    [entry] = AutoImporter().run_once(connector, seeded_db, broken_llm)
    assert entry.status == "imported" and "rate limit" in entry.detail
    with seeded_db() as db:
        assert db.get(Meeting, UUID(entry.meeting_id)).status == "transcribed"
    assert connector.client.fake._queue == []  # imported, so acknowledged; it can be re-analyzed from the UI


def test_other_events_are_ignored(connector: GoogleConnector, seeded_db) -> None:
    state = urlparse(connector.start_connect("/import")).query.split("state=")[1]
    connector.complete_connect("mock-code", state, None)
    connector.client.fake._queue.append(_message("x", event_type="google.workspace.meet.conference.v2.started"))
    assert AutoImporter().run_once(connector, seeded_db, MockLLMProvider) == []
    assert connector.client.fake._queue == []


def test_not_connected(connector: GoogleConnector, seeded_db) -> None:
    importer = AutoImporter()
    assert importer.run_once(connector, seeded_db, MockLLMProvider) == []
    assert importer.status()["last_error"] == "Google is not connected."


def test_subscription_is_renewed_before_it_expires(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    connector._events_subscription["expireTime"] = soon
    connector.client.fake._subscriptions["subscriptions/mock-1"]["expireTime"] = soon
    connector.ensure_events_subscription()
    renewed = datetime.fromisoformat(connector._events_subscription["expireTime"].replace("Z", "+00:00"))
    assert renewed - datetime.now(timezone.utc) > timedelta(days=6)


def test_missing_pubsub_permission_is_reported(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    connector._events_subscription = None
    connector._connection.tokens["scope"] = connector._connection.tokens["scope"].replace("https://www.googleapis.com/auth/pubsub", "")
    connector.ensure_events_subscription()
    assert "Pub/Sub access was not granted" in google.get("/api/google/auto-import").json()["error"]


def test_simulate_only_in_mock_mode(seeded_api: TestClient) -> None:
    settings = _settings(google_mode="live", google_client_id="cid", google_client_secret="secret")
    live = GoogleConnector(client=GoogleWorkspaceClient(settings), mode="live", frontend_url=settings.frontend_url)
    app.dependency_overrides[get_google_connector] = lambda: live
    assert seeded_api.post("/api/google/auto-import/simulate").status_code == 404


def test_manual_import_is_idempotent_too(google: TestClient) -> None:
    _connect(google)
    body = {"transcript_name": "conferenceRecords/mock-review/transcripts/mock-transcript", "title": "Review"}
    first = google.post("/api/google/import", json=body).json()
    second = google.post("/api/google/import", json=body).json()
    assert first["id"] == second["id"]


def test_live_scopes_include_pubsub_only_when_configured() -> None:
    plain = GoogleWorkspaceClient(_settings(google_mode="live"))
    auto = GoogleWorkspaceClient(_settings(google_mode="live", google_pubsub_topic="projects/p/topics/t",
                                           google_pubsub_subscription="projects/p/subscriptions/s"))
    assert "https://www.googleapis.com/auth/pubsub" not in plain.scopes()
    assert "https://www.googleapis.com/auth/pubsub" in auto.scopes()


def test_pubsub_settings_are_validated() -> None:
    with pytest.raises(ValueError, match="GOOGLE_PUBSUB_TOPIC"):
        _settings(google_pubsub_topic="meet-events")
    with pytest.raises(ValueError, match="GOOGLE_PUBSUB_SUBSCRIPTION"):
        _settings(google_pubsub_subscription="projects/p/topics/wrong")
