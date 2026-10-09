"""GOOGLE_MODE=mock: the real client talking to a fake Google API.

Responses follow the documented shapes of OAuth, Calendar v3 and Meet v2, so mock and
live modes share one code path. Data is generated relative to "now" so the demo meeting
always appears in the recent-events list.
"""

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import itertools
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlencode

import httpx

from app.connectors.google.client import TRANSCRIPT_READY, GoogleWorkspaceClient
from app.core.config import Settings


SAMPLE_CODE, STANDUP_CODE, UPCOMING_CODE = "abc-mnop-xyz", "qrs-tuvw-xyz", "jkl-wxyz-abc"
RECORD, STANDUP_RECORD = "conferenceRecords/mock-review", "conferenceRecords/mock-standup"
TRANSCRIPT = f"{RECORD}/transcripts/mock-transcript"
MOCK_ACCOUNT_ID = "100000000000000000001"
MOCK_TOPIC = "projects/yuqta-mock/topics/meet-events"
MOCK_SUBSCRIPTION = "projects/yuqta-mock/subscriptions/yuqta-meet-events"
# Review-style records: the original one plus any created by simulate_transcript_ready().
_REVIEW = r"conferenceRecords/(?:mock-review|sim-\d+)"


def _iso(value: datetime) -> str:
    # Google returns fractional seconds (RFC 3339); keep milliseconds like the real API.
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _FakeGoogle:
    def __init__(self, fixture_path: Path):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        day = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.review_start = day
        self.segments = fixture["segments"]
        self.speakers = list(dict.fromkeys(segment["speaker"] for segment in self.segments))
        self._queue: list[dict] = []  # Pub/Sub messages waiting to be pulled
        self._queue_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._subscriptions: dict[str, dict] = {}
        self.sent_mail: list[str] = []  # raw messages sent through the Gmail API

    def simulate_transcript_ready(self) -> str:
        """A meeting just ended and Google generated its transcript: publish the event."""
        transcript = f"conferenceRecords/sim-{next(self._ids)}/transcripts/t1"
        data = b64encode(json.dumps({"transcript": {"name": transcript}}).encode()).decode()
        with self._queue_lock:
            self._queue.append({
                "ackId": f"ack-{transcript}",
                "message": {
                    "data": data,
                    "messageId": transcript,
                    "attributes": {"ce-type": TRANSCRIPT_READY, "ce-source": "//meet.googleapis.com/spaces/mock-space",
                                   "ce-subject": f"//meet.googleapis.com/{transcript}", "ce-specversion": "1.0"},
                },
            })
        return transcript

    def _pubsub(self, path: str, body: dict) -> httpx.Response:
        with self._queue_lock:
            if path.endswith(":pull"):
                batch = self._queue[: int(body.get("maxMessages", 10))]
                return httpx.Response(200, json={"receivedMessages": batch} if batch else {})
            acked = set(body.get("ackIds", []))
            self._queue = [m for m in self._queue if m["ackId"] not in acked]
            return httpx.Response(200, json={})

    def _events(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            name = f"subscriptions/mock-{len(self._subscriptions) + 1}"
            sub = {"name": name, "targetResource": body["targetResource"], "eventTypes": body["eventTypes"],
                   "notificationEndpoint": body["notificationEndpoint"], "state": "ACTIVE",
                   "expireTime": _iso(datetime.now(timezone.utc) + timedelta(days=7))}
            self._subscriptions[name] = sub
            return httpx.Response(200, json={"name": "operations/mock", "done": True, "response": sub})
        if request.method == "PATCH":
            name = request.url.path.removeprefix("/v1/")
            sub = self._subscriptions.get(name)
            if not sub:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Subscription not found"}})
            sub["expireTime"] = _iso(datetime.now(timezone.utc) + timedelta(days=7))
            return httpx.Response(200, json={"name": "operations/mock", "done": True, "response": sub})
        target = re.search(r'target_resource="([^"]+)"', request.url.params.get("filter", ""))
        found = [s for s in self._subscriptions.values() if target and s["targetResource"] == target.group(1)]
        return httpx.Response(200, json={"subscriptions": found} if found else {})

    def events(self) -> list[dict]:
        def meet(code: str) -> dict:
            return {"conferenceId": code, "conferenceSolution": {"key": {"type": "hangoutsMeet"}}}

        start = self.review_start
        upcoming = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
        return [
            {
                "id": "mock-review", "status": "confirmed", "summary": "Enterprise Revenue Review",
                "start": {"dateTime": _iso(start)}, "end": {"dateTime": _iso(start + timedelta(minutes=30))},
                "hangoutLink": f"https://meet.google.com/{SAMPLE_CODE}", "conferenceData": meet(SAMPLE_CODE),
                "attendees": [{"email": f"{name.lower().replace(' ', '.')}@example.com", "displayName": name} for name in self.speakers],
            },
            {
                "id": "mock-lunch", "status": "confirmed", "summary": "Team lunch",
                "start": {"dateTime": _iso(start + timedelta(hours=2))}, "end": {"dateTime": _iso(start + timedelta(hours=3))},
            },
            {
                "id": "mock-standup", "status": "confirmed", "summary": "Product standup",
                "start": {"dateTime": _iso(start + timedelta(hours=5))}, "end": {"dateTime": _iso(start + timedelta(hours=5, minutes=15))},
                "hangoutLink": f"https://meet.google.com/{STANDUP_CODE}", "conferenceData": meet(STANDUP_CODE),
            },
            {
                # Starts at the top of the hour after next, so calendar auto-join can schedule a bot for it.
                "id": "mock-weekly-sync", "status": "confirmed", "summary": "Weekly sync",
                "start": {"dateTime": _iso(upcoming)}, "end": {"dateTime": _iso(upcoming + timedelta(minutes=30))},
                "hangoutLink": f"https://meet.google.com/{UPCOMING_CODE}", "conferenceData": meet(UPCOMING_CODE),
            },
        ]

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        if request.url.host == "oauth2.googleapis.com":
            if path == "/token":
                form = parse_qs(request.content.decode())
                if form.get("grant_type") == ["authorization_code"] and form.get("code") != ["mock-code"]:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad authorization code."})
                body = {"access_token": "mock-access", "expires_in": 3599, "scope": "openid email profile "
                        "https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/meetings.space.readonly "
                        "https://www.googleapis.com/auth/pubsub https://www.googleapis.com/auth/gmail.send"}
                if form.get("grant_type") == ["authorization_code"]:
                    body["refresh_token"] = "mock-refresh"
                return httpx.Response(200, json=body)
            return httpx.Response(200)  # /revoke
        if request.url.host == "gmail.googleapis.com" and path.endswith("/messages/send"):
            self.sent_mail.append(json.loads(request.content)["raw"])
            return httpx.Response(200, json={"id": f"mock-message-{len(self.sent_mail)}"})
        if request.url.host == "pubsub.googleapis.com":
            return self._pubsub(path, json.loads(request.content or b"{}"))
        if request.url.host == "workspaceevents.googleapis.com":
            return self._events(request)
        if path == "/v1/userinfo":
            return httpx.Response(200, json={"sub": MOCK_ACCOUNT_ID, "email": "demo.user@example.com", "name": "Demo User (mock Google)"})
        if path.endswith("/calendars/primary/events"):
            # Like Calendar v3: events overlapping [timeMin, timeMax).
            window = [datetime.fromisoformat(params[key].replace("Z", "+00:00")) for key in ("timeMin", "timeMax")]
            items = [
                e for e in self.events()
                if datetime.fromisoformat(e["end"]["dateTime"].replace("Z", "+00:00")) > window[0]
                and datetime.fromisoformat(e["start"]["dateTime"].replace("Z", "+00:00")) < window[1]
            ]
            return httpx.Response(200, json={"items": items})
        if path == "/v2/conferenceRecords":
            code = re.search(r'space\.meeting_code = "([a-z-]+)"', params.get("filter", ""))
            records = {
                SAMPLE_CODE: {"name": RECORD, "startTime": _iso(self.review_start + timedelta(minutes=1)), "endTime": _iso(self.review_start + timedelta(minutes=29))},
                STANDUP_CODE: {"name": STANDUP_RECORD, "startTime": _iso(self.review_start + timedelta(hours=5)), "endTime": _iso(self.review_start + timedelta(hours=5, minutes=14))},
            }
            record = records.get(code.group(1)) if code else None
            return httpx.Response(200, json={"conferenceRecords": [record]} if record else {})
        record_match = re.fullmatch(rf"/v2/({_REVIEW})", path)
        if record_match:  # GET conferenceRecords/x
            return httpx.Response(200, json={"name": record_match.group(1), "space": "spaces/mock-space-review",
                                             "startTime": _iso(self.review_start + timedelta(minutes=1)),
                                             "endTime": _iso(self.review_start + timedelta(minutes=29))})
        if path == "/v2/spaces/mock-space-review":
            return httpx.Response(200, json={"name": "spaces/mock-space-review", "meetingCode": SAMPLE_CODE,
                                             "meetingUri": f"https://meet.google.com/{SAMPLE_CODE}"})
        if path == f"/v2/{RECORD}/transcripts":
            return httpx.Response(200, json={"transcripts": [{
                "name": TRANSCRIPT, "state": "FILE_GENERATED",
                "docsDestination": {"document": "mock-doc", "exportUri": "https://docs.google.com/document/d/mock-doc"},
            }]})
        if path == f"/v2/{STANDUP_RECORD}/transcripts":
            return httpx.Response(200, json={})
        participants_match = re.fullmatch(rf"/v2/({_REVIEW})/participants", path)
        if participants_match:
            record = participants_match.group(1)
            return httpx.Response(200, json={"participants": [
                {"name": f"{record}/participants/p{i}", "signedinUser": {"user": f"users/{i}", "displayName": name}}
                for i, name in enumerate(self.speakers)
            ]})
        entries_match = re.fullmatch(rf"/v2/({_REVIEW})/transcripts/[\w-]+/entries", path)
        if entries_match:
            record = entries_match.group(1)
            origin = self.review_start + timedelta(minutes=2)
            return httpx.Response(200, json={"transcriptEntries": [
                {
                    "name": f"{record}/transcripts/t/entries/e{segment['index']}",
                    "participant": f"{record}/participants/p{self.speakers.index(segment['speaker'])}",
                    "text": segment["text"], "languageCode": "en-US",
                    "startTime": _iso(origin + timedelta(seconds=segment["start_seconds"])),
                    "endTime": _iso(origin + timedelta(seconds=segment["end_seconds"])),
                }
                for segment in self.segments
            ]})
        return httpx.Response(404, json={"error": {"code": 404, "message": f"Requested entity was not found: {path}"}})


class MockGoogleWorkspaceClient(GoogleWorkspaceClient):
    """Skips Google's consent screen: the 'authorization URL' is our own callback with a mock code."""

    def __init__(self, settings: Settings):
        # Mock mode always has auto-import available, on a fake topic/subscription.
        if not settings.auto_import_configured:
            settings = settings.model_copy(update={"google_pubsub_topic": MOCK_TOPIC, "google_pubsub_subscription": MOCK_SUBSCRIPTION})
        self.fake = _FakeGoogle(Path(settings.sample_transcript_path))
        super().__init__(settings, transport=httpx.MockTransport(self.fake.handle))

    def authorization_url(self, state: str, code_challenge: str) -> str:
        return f"{self.settings.google_redirect_uri}?{urlencode({'code': 'mock-code', 'state': state})}"
