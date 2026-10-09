"""Google Workspace connector: REST client for Google OAuth, Calendar v3, and Meet v2.

Endpoints follow the current Google Workspace docs:
- OAuth web server flow: https://developers.google.com/identity/protocols/oauth2/web-server
- Calendar events.list: https://developers.google.com/workspace/calendar/api/v3/reference/events/list
- Meet artifacts: https://developers.google.com/workspace/meet/api/guides/artifacts
"""

from base64 import urlsafe_b64encode
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import time
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.schemas.transcript import SegmentIn


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MEET_API = "https://meet.googleapis.com/v2"

GOOGLE_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/meetings.space.readonly",
)
REQUIRED_SCOPES = GOOGLE_SCOPES[3:]
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"  # only requested when auto-import is configured

EVENTS_API = "https://workspaceevents.googleapis.com/v1"
PUBSUB_API = "https://pubsub.googleapis.com/v1"
TRANSCRIPT_READY = "google.workspace.meet.transcript.v2.fileGenerated"

MEETING_CODE_PATTERN = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$")
TRANSCRIPT_NAME_PATTERN = re.compile(r"^conferenceRecords/[\w-]+/transcripts/[\w-]+$")
_MAX_ENTRY_PAGES = 100  # 100 entries per page -> 10,000 entries per transcript at most


class GoogleAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def meeting_code_for_event(event: dict) -> str | None:
    conference = event.get("conferenceData") or {}
    if conference.get("conferenceSolution", {}).get("key", {}).get("type") == "hangoutsMeet":
        code = conference.get("conferenceId")
        if code:
            return code
    link = event.get("hangoutLink") or ""
    match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", link)
    return match.group(1) if match else None


def simplify_event(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    attendees = [
        attendee.get("displayName") or attendee.get("email")
        for attendee in event.get("attendees", [])
        if not attendee.get("resource") and (attendee.get("displayName") or attendee.get("email"))
    ]
    return {
        "id": event.get("id"),
        "title": event.get("summary") or "Untitled event",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start and "dateTime" not in start,
        "meeting_code": meeting_code_for_event(event),
        "meet_link": event.get("hangoutLink"),
        "html_link": event.get("htmlLink"),
        "attendees": attendees,
        # Who receives the meeting minutes: attendees with an address who did not decline.
        "attendee_emails": [
            attendee["email"]
            for attendee in event.get("attendees", [])
            if attendee.get("email") and not attendee.get("resource") and attendee.get("responseStatus") != "declined"
        ],
        # The signed-in user declined the invitation.
        "declined": any(a.get("self") and a.get("responseStatus") == "declined" for a in event.get("attendees", [])),
    }


def participant_display_name(participant: dict) -> str:
    for kind in ("signedinUser", "anonymousUser", "phoneUser"):
        name = (participant.get(kind) or {}).get("displayName")
        if name:
            return name
    return "Unknown speaker"


class GoogleWorkspaceClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._http = httpx.Client(timeout=20.0, transport=transport)

    # OAuth -----------------------------------------------------------------

    def scopes(self) -> tuple[str, ...]:
        return GOOGLE_SCOPES + ((PUBSUB_SCOPE,) if self.settings.auto_import_configured else ())

    def authorization_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes()),
            "access_type": "offline",
            "include_granted_scopes": "true",
            # select_account: Google shows its account chooser, so another person's account can be added.
            "prompt": "select_account consent",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> dict:
        return self._token_request(
            {
                "code": code,
                "code_verifier": code_verifier,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "redirect_uri": self.settings.google_redirect_uri,
                "grant_type": "authorization_code",
            }
        )

    def refresh(self, refresh_token: str) -> dict:
        return self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "grant_type": "refresh_token",
            }
        )

    def revoke(self, token: str) -> None:
        try:
            self._http.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass  # Local sign-out still succeeds if revocation cannot reach Google.

    def _token_request(self, data: dict) -> dict:
        response = self._send("POST", TOKEN_URL, data=data)
        tokens = response.json()
        tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
        return tokens

    def userinfo(self, access_token: str) -> dict:
        return self._get(USERINFO_URL, access_token)

    # Calendar --------------------------------------------------------------

    def list_events(
        self,
        access_token: str,
        time_min: datetime,
        time_max: datetime,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> dict:
        params = {
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        return self._get(CALENDAR_EVENTS_URL, access_token, params)

    # Meet ------------------------------------------------------------------

    def list_conference_records(
        self,
        access_token: str,
        meeting_code: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict]:
        if not MEETING_CODE_PATTERN.match(meeting_code):
            raise ValueError("Meeting code must look like abc-mnop-xyz.")
        clauses = [f'space.meeting_code = "{meeting_code}"']
        if start:
            clauses.append(f'start_time >= "{_rfc3339(start)}"')
        if end:
            clauses.append(f'start_time <= "{_rfc3339(end)}"')
        return list(
            self._paginate(
                f"{MEET_API}/conferenceRecords",
                access_token,
                "conferenceRecords",
                {"filter": " AND ".join(clauses), "pageSize": 100},
            )
        )

    def list_transcripts(self, access_token: str, conference_record: str) -> list[dict]:
        return list(
            self._paginate(
                f"{MEET_API}/{conference_record}/transcripts",
                access_token,
                "transcripts",
                {"pageSize": 100},
            )
        )

    def list_participants(self, access_token: str, conference_record: str) -> list[dict]:
        return list(
            self._paginate(
                f"{MEET_API}/{conference_record}/participants",
                access_token,
                "participants",
                {"pageSize": 250},
            )
        )

    def list_transcript_entries(self, access_token: str, transcript_name: str) -> list[dict]:
        if not TRANSCRIPT_NAME_PATTERN.match(transcript_name):
            raise ValueError("Invalid transcript name.")
        return list(
            self._paginate(
                f"{MEET_API}/{transcript_name}/entries",
                access_token,
                "transcriptEntries",
                {"pageSize": 100},
                max_pages=_MAX_ENTRY_PAGES,
            )
        )

    def get_resource(self, access_token: str, name: str) -> dict:
        """GET a Meet v2 resource by name, e.g. conferenceRecords/x or spaces/y."""
        if not re.fullmatch(r"(conferenceRecords|spaces)/[\w-]+", name):
            raise ValueError(f"Invalid Meet resource name: {name}")
        return self._get(f"{MEET_API}/{name}", access_token)

    # Workspace Events (subscriptions) ----------------------------------------
    # https://developers.google.com/workspace/events/guides/create-subscription

    def create_events_subscription(self, access_token: str, target_resource: str, topic: str) -> dict:
        body = {
            "targetResource": target_resource,
            "eventTypes": [TRANSCRIPT_READY],
            "notificationEndpoint": {"pubsubTopic": topic},
            "payloadOptions": {"includeResource": False},
        }
        operation = self._json("POST", f"{EVENTS_API}/subscriptions", access_token, body)
        return operation.get("response") or {}

    def find_events_subscription(self, access_token: str, target_resource: str) -> dict | None:
        filter_ = f'event_types:"{TRANSCRIPT_READY}" AND target_resource="{target_resource}"'
        payload = self._get(f"{EVENTS_API}/subscriptions", access_token, {"filter": filter_})
        subscriptions = payload.get("subscriptions") or []
        return subscriptions[0] if subscriptions else None

    def renew_events_subscription(self, access_token: str, name: str) -> dict:
        if not re.fullmatch(r"subscriptions/[\w-]+", name):
            raise ValueError(f"Invalid subscription name: {name}")
        # ttl 0 = the maximum expiration Google allows.
        operation = self._json("PATCH", f"{EVENTS_API}/{name}?updateMask=ttl", access_token, {"ttl": "0s"})
        return operation.get("response") or {}

    # Pub/Sub (pull, so Yuqta needs no public URL) ------------------------------

    def pubsub_pull(self, access_token: str, subscription: str, max_messages: int = 10) -> list[dict]:
        payload = self._json("POST", f"{PUBSUB_API}/{subscription}:pull", access_token, {"maxMessages": max_messages})
        return payload.get("receivedMessages") or []

    def pubsub_ack(self, access_token: str, subscription: str, ack_ids: list[str]) -> None:
        if ack_ids:
            self._json("POST", f"{PUBSUB_API}/{subscription}:acknowledge", access_token, {"ackIds": ack_ids})

    # Transport helpers -----------------------------------------------------

    def _json(self, method: str, url: str, access_token: str, body: dict) -> dict:
        response = self._send(method, url, json=body, headers={"Authorization": f"Bearer {access_token}"})
        return response.json() if response.content else {}

    def _paginate(
        self, url: str, access_token: str, key: str, params: dict, max_pages: int = 20
    ) -> Iterator[dict]:
        params = dict(params)
        for _ in range(max_pages):
            payload = self._get(url, access_token, params)
            yield from payload.get(key, [])
            token = payload.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    def _get(self, url: str, access_token: str, params: dict | None = None) -> dict:
        response = self._send(
            "GET", url, params=params, headers={"Authorization": f"Bearer {access_token}"}
        )
        return response.json()

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise GoogleAPIError(502, f"Could not reach Google: {error}") from error
        if response.is_success:
            return response
        raise GoogleAPIError(response.status_code, _error_message(response))


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Google returned HTTP {response.status_code}."
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message") or f"Google returned HTTP {response.status_code}."
    return payload.get("error_description") or str(error or f"HTTP {response.status_code}")


def conference_window(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    """Widen a calendar event's time range to catch early joins and overruns."""
    slack = timedelta(hours=1)
    return (
        _parse_time(start) - slack if start and "T" in start else None,
        _parse_time(end) + slack if end and "T" in end else None,
    )


def entries_to_segments(entries: list[dict], speakers: dict[str, str]) -> list[SegmentIn]:
    """Transcript entries -> Yuqta segments, consecutive turns by the same speaker merged."""
    ordered = sorted((e for e in entries if (e.get("text") or "").strip()), key=lambda e: e.get("startTime", ""))
    if not ordered:
        return []
    origin = _parse_time(ordered[0]["startTime"]) if ordered[0].get("startTime") else None

    def offset(value: str | None) -> float | None:
        return round((_parse_time(value) - origin).total_seconds(), 1) if value and origin else None

    segments: list[SegmentIn] = []
    for entry in ordered:
        speaker = speakers.get(entry.get("participant", ""), "Unknown speaker")
        text = " ".join(entry["text"].split())
        if segments and segments[-1].speaker == speaker:
            last = segments[-1]
            segments[-1] = last.model_copy(update={"text": f"{last.text} {text}", "end_seconds": offset(entry.get("endTime")) or last.end_seconds})
        else:
            segments.append(SegmentIn(speaker=speaker, text=text, start_seconds=offset(entry.get("startTime")), end_seconds=offset(entry.get("endTime"))))
    return segments
