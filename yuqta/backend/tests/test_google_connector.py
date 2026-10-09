"""Google Meet connector end to end against the mock Google API (same code path as live mode)."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from app.connectors.google import GoogleConnector, get_google_connector
from app.connectors.google.client import GoogleWorkspaceClient, entries_to_segments
from app.connectors.google.mock import SAMPLE_CODE, STANDUP_CODE, UPCOMING_CODE, MockGoogleWorkspaceClient
from app.core.config import Settings, get_settings
from app.main import app


def _settings(**overrides) -> Settings:
    base = dict(_env_file=None, google_redirect_uri="http://backend.test/auth/google/callback", frontend_url="http://frontend.test",
                sample_transcript_path=get_settings().sample_transcript_path)
    return Settings(**{**base, **overrides})


@pytest.fixture
def connector() -> GoogleConnector:
    settings = _settings()
    return GoogleConnector(client=MockGoogleWorkspaceClient(settings), mode="mock", frontend_url=settings.frontend_url)


@pytest.fixture
def google(seeded_api: TestClient, connector: GoogleConnector) -> TestClient:
    app.dependency_overrides[get_google_connector] = lambda: connector
    return seeded_api


def _connect(client: TestClient) -> str:
    url = client.post("/api/google/connect", json={"return_path": "/import"}).json()["authorization_url"]
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "http://backend.test/auth/google/callback"
    callback = client.get(f"/auth/google/callback?{parsed.query}", follow_redirects=False)
    assert callback.status_code == 302
    return callback.headers["location"]


def test_connect_flow(google: TestClient) -> None:
    assert google.get("/api/google/status").json() == {
        "mode": "mock", "configured": True, "connected": False, "account": None, "missing_scopes": [], "accounts": [],
    }
    assert _connect(google) == "http://frontend.test/import?google=connected"
    status = google.get("/api/google/status").json()
    assert status["connected"] is True
    assert status["account"] == {"email": "demo.user@example.com", "name": "Demo User (mock Google)"}
    assert status["missing_scopes"] == []


def test_state_is_single_use_and_validated(google: TestClient) -> None:
    url = google.post("/api/google/connect", json={}).json()["authorization_url"]
    query = urlparse(url).query
    assert google.get(f"/auth/google/callback?{query}", follow_redirects=False).headers["location"].endswith("google=connected")
    replay = google.get(f"/auth/google/callback?{query}", follow_redirects=False)
    assert replay.headers["location"] == "http://frontend.test/import?google_error=invalid_state"
    forged = google.get("/auth/google/callback?code=mock-code&state=forged", follow_redirects=False)
    assert forged.headers["location"] == "http://frontend.test/import?google_error=invalid_state"


def test_denied_consent_and_bad_code(google: TestClient) -> None:
    state = parse_qs(urlparse(google.post("/api/google/connect", json={}).json()["authorization_url"]).query)["state"][0]
    denied = google.get(f"/auth/google/callback?error=access_denied&state={state}", follow_redirects=False)
    assert denied.headers["location"] == "http://frontend.test/import?google_error=access_denied"

    state = parse_qs(urlparse(google.post("/api/google/connect", json={}).json()["authorization_url"]).query)["state"][0]
    bad = google.get(f"/auth/google/callback?code=wrong&state={state}", follow_redirects=False)
    assert bad.headers["location"] == "http://frontend.test/import?google_error=token_exchange_failed"
    assert google.get("/api/google/status").json()["connected"] is False


def test_return_path_cannot_redirect_off_site(google: TestClient) -> None:
    for bad in ("//evil.example", "https://evil.example", "evil"):
        assert google.post("/api/google/connect", json={"return_path": bad}).status_code == 422


def test_data_requires_connection(google: TestClient) -> None:
    response = google.get("/api/google/events")
    assert (response.status_code, response.json()["detail"]) == (409, "Google is not connected.")


def test_events_and_transcripts(google: TestClient) -> None:
    _connect(google)
    events = google.get("/api/google/events").json()["events"]
    assert [(e["title"], e["meeting_code"]) for e in events] == [
        ("Weekly sync", UPCOMING_CODE),
        ("Product standup", STANDUP_CODE),
        ("Enterprise Revenue Review", SAMPLE_CODE),
    ]  # most recent first; the non-Meet "Team lunch" is filtered out
    assert google.get("/api/google/events", params={"days_ahead": 0}).json()["events"][0]["title"] == "Product standup"
    review = events[2]
    assert review["attendees"] == ["Sales Manager", "Finance Manager", "Product Manager"]

    records = google.get(
        "/api/google/conference-records", params={"meeting_code": SAMPLE_CODE, "start": review["start"], "end": review["end"]}
    ).json()["conference_records"]
    assert [t["state"] for t in records[0]["transcripts"]] == ["FILE_GENERATED"]
    standup = google.get("/api/google/conference-records", params={"meeting_code": STANDUP_CODE}).json()["conference_records"]
    assert standup[0]["transcripts"] == []
    assert google.get("/api/google/conference-records", params={"meeting_code": 'x" OR "y'}).status_code == 422


def test_import_then_analyze(google: TestClient) -> None:
    _connect(google)
    review = google.get("/api/google/events").json()["events"][2]
    record = google.get("/api/google/conference-records", params={"meeting_code": SAMPLE_CODE}).json()["conference_records"][0]
    imported = google.post(
        "/api/google/import",
        json={"transcript_name": record["transcripts"][0]["name"], "title": review["title"], "participants": review["attendees"]},
    )
    assert imported.status_code == 201, imported.text
    meeting = imported.json()
    assert (meeting["source"], meeting["status"], meeting["segment_count"]) == ("google_meet", "transcribed", 4)
    assert [(s["speaker"], s["start_seconds"]) for s in meeting["segments"]] == [
        ("Sales Manager", 0.0), ("Finance Manager", 3.6), ("Product Manager", 7.3), ("Sales Manager", 10.2),
    ]

    analysis = google.post(f"/api/meetings/{meeting['id']}/analyze").json()
    assert analysis["summary"]["revenue_change"] == -440000
    assert [r["title"] for r in analysis["recommendations"]][:2] == [
        "Contact Acme about reduced orders", "Escalate Beta's overdue renewal",
    ]


def test_import_validation(google: TestClient) -> None:
    _connect(google)
    assert google.post("/api/google/import", json={"transcript_name": "../../etc", "title": "x"}).status_code == 422
    missing = google.post("/api/google/import", json={"transcript_name": "conferenceRecords/nope/transcripts/nope", "title": "x"})
    assert missing.status_code == 404


def test_expired_token_is_refreshed(google: TestClient, connector: GoogleConnector) -> None:
    _connect(google)
    connector._connection.tokens["expires_at"] = 0
    assert google.get("/api/google/events").status_code == 200
    assert connector._connection.tokens["expires_at"] > 0


def test_disconnect(google: TestClient) -> None:
    _connect(google)
    assert google.post("/api/google/disconnect").json() == {"connected": False, "accounts": []}
    assert google.get("/api/google/status").json()["connected"] is False


def test_live_mode_requires_credentials(seeded_api: TestClient) -> None:
    settings = _settings(google_mode="live")
    live = GoogleConnector(client=GoogleWorkspaceClient(settings), mode="live", frontend_url=settings.frontend_url)
    app.dependency_overrides[get_google_connector] = lambda: live
    assert seeded_api.get("/api/google/status").json()["configured"] is False
    response = seeded_api.post("/api/google/connect", json={})
    assert (response.status_code, "GOOGLE_CLIENT_ID" in response.json()["detail"]) == (503, True)


def test_live_authorization_url_uses_pkce_and_scopes() -> None:
    settings = _settings(google_mode="live", google_client_id="cid", google_client_secret="secret")
    url = urlparse(GoogleWorkspaceClient(settings).authorization_url("state123", "challenge456"))
    params = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert params["redirect_uri"] == ["http://backend.test/auth/google/callback"]
    assert params["code_challenge_method"] == ["S256"] and params["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/meetings.space.readonly" in params["scope"][0]
    assert "secret" not in url.query


def test_entries_merge_consecutive_turns() -> None:
    segments = entries_to_segments(
        [
            {"participant": "p/1", "text": "First", "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-01T00:00:02Z"},
            {"participant": "p/1", "text": "still me", "startTime": "2026-01-01T00:00:02Z", "endTime": "2026-01-01T00:00:03Z"},
            {"participant": "p/2", "text": "Second", "startTime": "2026-01-01T00:00:05Z"},
            {"participant": "p/9", "text": "  "},
        ],
        {"p/1": "Ari", "p/2": "Sam"},
    )
    assert [(s.speaker, s.text, s.start_seconds, s.end_seconds) for s in segments] == [
        ("Ari", "First still me", 0.0, 3.0),
        ("Sam", "Second", 5.0, None),
    ]



def _connect_as(client: TestClient, connector: GoogleConnector, email: str, name: str) -> None:
    profile = {"email": email, "name": name, "sub": f"sub-{email}"}
    original = connector.client.userinfo
    connector.client.userinfo = lambda token: profile
    try:
        _connect(client)
    finally:
        connector.client.userinfo = original


def test_several_accounts_can_be_connected(google: TestClient, connector: GoogleConnector) -> None:
    _connect_as(google, connector, "parul@example.com", "Parul")
    _connect_as(google, connector, "kirty@example.com", "Kirty")
    _connect_as(google, connector, "parul@example.com", "Parul")  # reconnecting does not duplicate
    status = google.get("/api/google/status").json()
    assert [a["email"] for a in status["accounts"]] == ["parul@example.com", "kirty@example.com"]
    assert status["account"]["email"] == "parul@example.com"  # the first account stays primary
    assert connector.events(1, 1, account="KIRTY@example.com")  # each account's calendar can be read

    left = google.post("/api/google/disconnect", json={"account": "parul@example.com"}).json()
    assert left["connected"] is True and [a["email"] for a in left["accounts"]] == ["kirty@example.com"]
    assert google.get("/api/google/status").json()["account"]["email"] == "kirty@example.com"  # next one becomes primary
    assert google.post("/api/google/disconnect", json={"account": "nobody@example.com"}).status_code == 409
