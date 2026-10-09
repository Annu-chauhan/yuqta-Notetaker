"""Live-meeting notetaker bot: URL handling, Recall.ai client, and the send -> follow -> analyze workflow."""

import json

from fastapi.testclient import TestClient
import httpx
import pytest

from app.connectors.meeting_bot import get_meeting_bot_client, normalize_meeting_url
from app.connectors.meeting_bot.base import BotError, parse_transcript
from app.connectors.meeting_bot.mock import MockMeetingBotClient
from app.connectors.meeting_bot.recall import RecallMeetingBotClient, bot_state
from app.core.config import get_settings
from app.db.models import Meeting, MeetingBot
from app.db.session import get_session_factory
from app.main import app
from app.workflows import meeting_bot
from app.workflows.meeting_bot import MeetingBotPoller


class Clock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def bots(seeded_api: TestClient, seeded_db, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    client = MockMeetingBotClient(get_settings().sample_transcript_path, clock=clock)
    app.dependency_overrides[get_meeting_bot_client] = lambda: client
    app.dependency_overrides[get_session_factory] = lambda: seeded_db
    import app.api.bots as bots_api

    poller = MeetingBotPoller()
    monkeypatch.setattr(meeting_bot, "meeting_bot_poller", poller)
    monkeypatch.setattr(bots_api, "meeting_bot_poller", poller)
    return seeded_api


def _send(api: TestClient, url: str = "https://meet.google.com/abc-defg-hij", title: str = "Weekly revenue review") -> dict:
    response = api.post("/api/bots", json={"meeting_url": url, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _check(api: TestClient) -> dict:
    response = api.post("/api/bots/check")
    assert response.status_code == 200, response.text
    return response.json()["bots"][0]


# --- Meeting links ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://meet.google.com/abc-defg-hij", "https://meet.google.com/abc-defg-hij"),
        ("meet.google.com/abc-defg-hij", "https://meet.google.com/abc-defg-hij"),
        ("  https://meet.google.com/ABC-DEFG-HIJ?authuser=0 ", "https://meet.google.com/abc-defg-hij"),
        ("https://us02web.zoom.us/j/123456789?pwd=abc", "https://us02web.zoom.us/j/123456789?pwd=abc"),
        ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0", "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0"),
    ],
)
def test_supported_meeting_links(raw: str, expected: str) -> None:
    assert normalize_meeting_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "hello", "https://example.com/abc-defg-hij", "https://meet.google.com/", "javascript:alert(1)",
                                 "https://meet.google.com.evil.com/abc-defg-hij"])
def test_unsupported_meeting_links(raw: str) -> None:
    assert normalize_meeting_url(raw) is None


# --- Transcript parsing ------------------------------------------------------------------------


def _word(text: str, start: float, end: float) -> dict:
    return {"text": text, "start_timestamp": {"relative": start, "absolute": f"2026-10-07T10:00:{int(start):02d}Z"},
            "end_timestamp": {"relative": end, "absolute": f"2026-10-07T10:00:{int(end):02d}Z"}}


def test_parse_transcript_uses_participant_names_and_timing() -> None:
    entries = [
        {"participant": {"id": 1, "name": "Rahul"}, "words": [_word("Acme", 1.0, 1.4), _word("cut orders.", 1.5, 2.2)]},
        {"participant": {"id": 2, "name": None}, "words": [_word("  ", 3.0, 3.1)]},  # silence only: dropped
        {"participant": {"id": 3, "name": "Priya"}, "words": [_word("Beta", 4.0, 4.5)]},
    ]
    segments, started = parse_transcript(entries)
    assert [(s.speaker, s.text, s.start_seconds, s.end_seconds) for s in segments] == [
        ("Rahul", "Acme cut orders.", 1.0, 2.2),
        ("Priya", "Beta", 4.0, 4.5),
    ]
    assert started is not None and started.isoformat() == "2026-10-07T10:00:01+00:00"


# --- Recall.ai client ---------------------------------------------------------------------------


def _recall_bot(codes: list[str], transcript: dict | None = None, sub_code: str | None = None) -> dict:
    changes = [{"code": code, "sub_code": None, "message": None} for code in codes]
    if sub_code:
        changes[-1]["sub_code"] = sub_code
    recordings = [{"id": "rec-1", "media_shortcuts": {"transcript": transcript}}] if transcript is not None else []
    return {"id": "bot-1", "status_changes": changes, "recordings": recordings}


def test_bot_state_reads_latest_status_and_transcript() -> None:
    state = bot_state(_recall_bot(["joining_call", "in_call_recording", "call_ended", "done"],
                                  {"status": {"code": "done"}, "data": {"download_url": "https://s3.example/t.json"}}))
    assert (state.code, state.recorded, state.transcript_status, state.transcript_url) == ("done", True, "done", "https://s3.example/t.json")

    pending = bot_state(_recall_bot(["in_call_recording", "call_ended", "done"], {"status": {"code": "processing"}, "data": None}))
    assert pending.transcript_status == "processing" and pending.transcript_url is None

    kicked = bot_state(_recall_bot(["joining_call", "in_waiting_room", "fatal"], sub_code="bot_kicked_from_waiting_room"))
    assert (kicked.code, kicked.sub_code, kicked.recorded) == ("fatal", "bot_kicked_from_waiting_room", False)


def test_recall_client_requests() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "us-west-2.recall.ai" and request.method == "POST" and request.url.path == "/api/v1/bot/":
            return httpx.Response(201, json={"id": "bot-123"})
        if request.url.host == "s3.example":
            return httpx.Response(200, json=[{"participant": {"name": "Rahul"}, "words": [_word("hi", 0, 1)]}])
        return httpx.Response(404, json={"detail": "Not found."})

    client = RecallMeetingBotClient("secret-key", "us-west-2", "en", transport=httpx.MockTransport(handler))
    assert client.create_bot("https://meet.google.com/abc-defg-hij", "Yuqta Notetaker") == "bot-123"
    create = seen[0]
    assert create.headers["Authorization"] == "Token secret-key"
    body = json.loads(create.content)
    assert body["meeting_url"] == "https://meet.google.com/abc-defg-hij" and body["bot_name"] == "Yuqta Notetaker"
    provider = body["recording_config"]["transcript"]["provider"]["recallai_streaming"]
    assert provider == {"mode": "prioritize_accuracy", "language_code": "en"}
    assert RecallMeetingBotClient("k", "us-west-2").language == "auto"  # default: detect Hindi/English switching
    assert client.download_transcript("https://s3.example/t.json")[0]["participant"]["name"] == "Rahul"
    assert "Authorization" not in seen[1].headers  # never send the API key to the storage URL

    with pytest.raises(BotError) as missing:
        client.get_bot("nope")
    assert missing.value.permanent and missing.value.status_code == 404


def test_recall_client_can_transcribe_with_deepgram() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(201, json={"id": "bot-1"})
        return httpx.Response(400, json={"recording_config": ["Deepgram credentials not found."]})

    client = RecallMeetingBotClient("k", "us-west-2", "auto", transport=httpx.MockTransport(handler), transcription="deepgram")
    client.create_bot("https://meet.google.com/abc-defg-hij", "Yuqta")
    assert bodies[0]["recording_config"]["transcript"]["provider"] == {"deepgram_streaming": {"model": "nova-3", "language": "multi"}}
    with pytest.raises(BotError, match="To use Deepgram, add your Deepgram API key and project id in the Recall.ai dashboard"):
        client.create_bot("https://meet.google.com/abc-defg-hij", "Yuqta")


def test_recall_client_can_transcribe_with_aws() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "bot-1"})

    client = RecallMeetingBotClient("k", "us-west-2", transport=httpx.MockTransport(handler), transcription="aws",
                                    aws_languages=" en-IN , hi-IN ")
    client.create_bot("https://meet.google.com/abc-defg-hij", "Yuqta")
    assert bodies[0]["recording_config"]["transcript"]["provider"] == {
        "aws_transcribe_streaming": {"identify_multiple_languages": True, "language_options": "en-IN,hi-IN", "preferred_language": "en-IN"}
    }



def test_recall_client_reports_bad_key_and_field_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(400, json={"meeting_url": ["Invalid meeting URL."]})
        return httpx.Response(401, json={"detail": "Invalid token."})

    client = RecallMeetingBotClient("bad", "us-west-2", transport=httpx.MockTransport(handler))
    with pytest.raises(BotError, match="RECALL_API_KEY"):
        client.get_bot("bot-1")
    with pytest.raises(BotError, match="meeting_url: Invalid meeting URL."):
        client.create_bot("https://meet.google.com/abc-defg-hij", "Yuqta")


def test_recall_client_needs_a_key() -> None:
    with pytest.raises(BotError, match="RECALL_API_KEY"):
        RecallMeetingBotClient("", "us-west-2")


# --- Workflow through the API (mock bot, fake clock) --------------------------------------------


def test_bot_follows_the_call_then_analyzes_it(bots: TestClient, clock: Clock, seeded_db) -> None:
    sent = _send(bots)
    assert sent["status"] == "joining" and sent["meeting_url"] == "https://meet.google.com/abc-defg-hij"

    clock.now += 5
    assert _check(bots)["status"] == "waiting"
    clock.now += 5
    assert _check(bots)["status"] == "recording"
    clock.now += 15
    assert _check(bots)["status"] == "processing"
    clock.now += 5
    done = _check(bots)
    assert done["status"] == "analyzed", done["detail"]
    assert done["meeting_id"]

    meeting = bots.get(f"/api/meetings/{done['meeting_id']}").json()
    assert meeting["title"] == "Weekly revenue review"
    assert meeting["source"] == "mock_bot" and meeting["status"] == "analyzed"
    assert meeting["participants"] == ["Sales Manager", "Finance Manager", "Product Manager"]
    assert meeting["segments"][1]["text"] == "Acme reduced their order significantly."

    dashboard = bots.get("/api/dashboard/latest").json()
    assert dashboard["meeting_id"] == done["meeting_id"]
    assert "Revenue down $440K" in dashboard["widgets"][0]["headline"]

    # Later polls leave a finished bot alone, and never import the call twice.
    clock.now += 60
    _check(bots)
    with seeded_db() as db:
        assert db.query(Meeting).filter(Meeting.source == "mock_bot").count() == 1


def test_bot_that_leaves_before_recording_fails_clearly(bots: TestClient, clock: Clock) -> None:
    sent = _send(bots)
    clock.now += 5
    assert bots.post(f"/api/bots/{sent['id']}/leave").status_code == 200
    clock.now += 10
    failed = _check(bots)
    assert failed["status"] == "failed" and "not let into the call" in failed["detail"]
    assert failed["meeting_id"] is None


def test_leaving_early_still_analyzes_what_was_recorded(bots: TestClient, clock: Clock) -> None:
    sent = _send(bots)
    clock.now += 12
    assert _check(bots)["status"] == "recording"
    assert bots.post(f"/api/bots/{sent['id']}/leave").json()["detail"] == "Leaving the call…"
    assert _check(bots)["status"] == "processing"
    clock.now += 5
    assert _check(bots)["status"] == "analyzed"
    assert bots.post(f"/api/bots/{sent['id']}/leave").status_code == 409


def test_rejects_links_that_are_not_meetings(bots: TestClient) -> None:
    response = bots.post("/api/bots", json={"meeting_url": "https://example.com/party"})
    assert response.status_code == 422 and "meeting link" in response.json()["detail"]


def test_list_reports_provider_and_bots(bots: TestClient) -> None:
    _send(bots, title="  Board   sync ")
    listing = bots.get("/api/bots").json()
    assert listing["provider"] == "mock" and listing["bot_name"] == "Yuqta Notetaker"
    assert [b["title"] for b in listing["bots"]] == ["Board sync"]


class _FatalClient(MockMeetingBotClient):
    def get_bot(self, bot_id: str):
        return bot_state(_recall_bot(["joining_call", "fatal"], sub_code="meeting_not_found"))


def test_fatal_status_is_explained(bots: TestClient, clock: Clock, seeded_db) -> None:
    sent = _send(bots)
    app.dependency_overrides[get_meeting_bot_client] = lambda: _FatalClient(get_settings().sample_transcript_path, clock)
    bot = _check(bots)
    assert bot["status"] == "failed" and bot["detail"] == "The meeting link does not exist."
    with seeded_db() as db:
        assert db.get(MeetingBot, __import__("uuid").UUID(sent["id"])).provider_status == "fatal"



def test_delete_bot_entry_and_its_meeting(bots: TestClient, clock: Clock) -> None:
    sent = _send(bots)
    assert bots.delete(f"/api/bots/{sent['id']}").status_code == 409  # still joining
    clock.now += 30
    done = _check(bots)
    assert done["status"] == "analyzed"
    assert bots.delete(f"/api/bots/{sent['id']}").status_code == 204
    assert bots.get("/api/bots").json()["bots"] == []
    assert bots.get(f"/api/meetings/{done['meeting_id']}").status_code == 404  # its meeting went too
    assert bots.delete(f"/api/bots/{sent['id']}").status_code == 404

    failed = _send(bots, url="https://meet.google.com/xyz-abcd-efg")
    clock.now += 5
    bots.post(f"/api/bots/{failed['id']}/leave")
    clock.now += 10
    assert _check(bots)["status"] == "failed"
    assert bots.delete(f"/api/bots/{failed['id']}").status_code == 204  # failed entry, no meeting
