"""The workspace's Google connection: OAuth state, tokens and the Calendar/Meet calls Yuqta needs.

Several Google accounts can be connected (one per person); calendar auto-join reads all of their calendars.
The first connected account is the primary one, used by the Import page and Meet transcript auto-import.
With TOKEN_ENCRYPTION_KEY set, the tokens are also stored encrypted (app/db/credentials.py) and restored on
startup, so connections survive restarts; without it they live in memory only.
"""

from base64 import b64decode
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import secrets
import threading
import time
from typing import TYPE_CHECKING

from app.connectors.google.client import (
    PUBSUB_SCOPE,
    REQUIRED_SCOPES,
    TRANSCRIPT_READY,
    GoogleAPIError,
    GoogleWorkspaceClient,
    conference_window,
    entries_to_segments,
    new_pkce_pair,
    participant_display_name,
    simplify_event,
)
from app.schemas.transcript import SegmentIn


if TYPE_CHECKING:
    from app.db.credentials import CredentialStore


logger = logging.getLogger(__name__)
_STATE_TTL_SECONDS = 600


class ConnectorError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Connection:
    tokens: dict
    account: dict
    account_id: str | None = None  # Google account id ("sub"); the Workspace Events subscription target


@dataclass
class TranscriptEvent:
    ack_id: str
    event_type: str
    transcript_name: str | None


@dataclass
class GoogleConnector:
    client: GoogleWorkspaceClient
    mode: str
    frontend_url: str
    _pending: dict[str, tuple[str, str, float]] = field(default_factory=dict)  # state -> (verifier, return_to, expiry)
    _connections: dict[str, _Connection] = field(default_factory=dict)  # account key -> connection; first = primary
    _events_subscription: dict | None = None  # {"name": ..., "expireTime": ...}
    events_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    store: "CredentialStore | None" = None  # encrypted persistence; None = memory only

    def __post_init__(self) -> None:
        saved = self.store.load(self._store_key) if self.store else None
        if not saved:
            return
        entries = saved.get("accounts") if "accounts" in saved else [saved]  # older format held one account
        for entry in entries or []:
            if (entry.get("tokens") or {}).get("access_token"):
                connection = _Connection(tokens=entry["tokens"], account=entry.get("account") or {}, account_id=entry.get("account_id"))
                self._connections[self._key(connection)] = connection
                logger.info("Google connection restored for %s", connection.account.get("email"))

    @staticmethod
    def _key(connection: _Connection) -> str:
        return connection.account_id or (connection.account.get("email") or "").lower() or "default"

    @property
    def _connection(self) -> _Connection | None:
        """The primary (first connected) account."""
        return next(iter(self._connections.values()), None)

    def accounts(self) -> list[dict]:
        """Connected accounts in connection order: [{"email", "name", "missing_scopes"}]."""
        return [
            {**connection.account, "missing_scopes": self._missing_scopes(connection)}
            for connection in self._connections.values()
        ]

    @staticmethod
    def _missing_scopes(connection: _Connection) -> list[str]:
        granted = set((connection.tokens.get("scope") or "").split())
        return [s for s in REQUIRED_SCOPES if s not in granted]

    def _find(self, account: str | None) -> _Connection:
        """The connection for an account email (case-insensitive), or the primary one."""
        if account is None:
            connection = self._connection
        else:
            connection = next(
                (c for c in self._connections.values() if (c.account.get("email") or "").lower() == account.lower()), None
            )
        if connection is None:
            raise ConnectorError("Google is not connected." if account is None else f"{account} is not connected.", 409)
        return connection

    @property
    def _store_key(self) -> str:
        return f"google:{self.mode}"  # mock tokens never leak into live mode

    def _persist(self) -> None:
        if self.store is None:
            return
        accounts = [
            {"tokens": c.tokens, "account": c.account, "account_id": c.account_id} for c in self._connections.values()
        ]
        self.store.save(self._store_key, {"accounts": accounts} if accounts else None)

    # --- connection lifecycle ----------------------------------------------------------------

    def status(self) -> dict:
        primary = self._connection
        return {
            "mode": self.mode,
            "configured": self.client.settings.google_configured or self.mode == "mock",
            "connected": primary is not None,
            "account": primary.account if primary else None,  # the primary account
            "missing_scopes": self._missing_scopes(primary) if primary else [],
            "accounts": self.accounts(),
        }

    def start_connect(self, return_path: str = "/import") -> str:
        if not (self.client.settings.google_configured or self.mode == "mock"):
            raise ConnectorError("Google is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", 503)
        if not return_path.startswith("/") or return_path.startswith("//"):
            raise ConnectorError("return_path must be a path on the Yuqta frontend.", 422)
        state = secrets.token_urlsafe(24)
        verifier, challenge = new_pkce_pair()
        with self._lock:
            now = time.time()
            self._pending = {k: v for k, v in self._pending.items() if v[2] > now}  # drop expired
            self._pending[state] = (verifier, return_path, now + _STATE_TTL_SECONDS)
        return self.client.authorization_url(state, challenge)

    def complete_connect(self, code: str | None, state: str | None, error: str | None) -> str:
        """Handles Google's redirect. Returns the frontend URL to send the browser back to."""
        with self._lock:
            pending = self._pending.pop(state, None) if state else None
        if pending is None or pending[2] < time.time():
            return self._back("/import", google_error="invalid_state")
        verifier, return_path, _ = pending
        if error or not code:
            return self._back(return_path, google_error=error or "missing_code")
        try:
            tokens = self.client.exchange_code(code, verifier)
            profile = self.client.userinfo(tokens["access_token"])
        except GoogleAPIError as exc:
            logger.warning("Google token exchange failed: %s", exc.message)
            return self._back(return_path, google_error="token_exchange_failed")
        connection = _Connection(
            tokens=tokens,
            account={"email": profile.get("email"), "name": profile.get("name")},
            account_id=profile.get("sub"),
        )
        key = self._key(connection)
        with self._lock:
            previous = self._connections.get(key)
            if previous and not tokens.get("refresh_token"):
                tokens["refresh_token"] = previous.tokens.get("refresh_token")
            self._connections[key] = connection  # reconnecting an account keeps its place in the list
        self._persist()
        logger.info("Google connected (%s mode) as %s", self.mode, profile.get("email"))
        if self.client.settings.auto_import_configured:
            self.ensure_events_subscription()  # best effort; problems are shown in auto_import_status()
        return self._back(return_path, google="connected")

    def disconnect(self, account: str | None = None) -> None:
        """Disconnects one account (by email), or all accounts when account is None."""
        with self._lock:
            if account is None:
                removed = list(self._connections.values())
                self._connections.clear()
            else:
                connection = self._find(account)
                was_primary = connection is self._connection
                removed = [self._connections.pop(self._key(connection))]
            if account is None or was_primary:
                self._events_subscription = None  # the transcript-events subscription belongs to the primary account
        self._persist()
        for connection in removed:
            self.client.revoke(connection.tokens.get("refresh_token") or connection.tokens["access_token"])

    def _back(self, path: str, **query: str) -> str:
        from urllib.parse import urlencode

        return f"{self.frontend_url.rstrip('/')}{path}?{urlencode(query)}"

    def _access_token(self, account: str | None = None) -> str:
        connection = self._find(account)
        tokens = connection.tokens
        if tokens["expires_at"] - time.time() < 60:
            refresh_token = tokens.get("refresh_token")
            try:
                if not refresh_token:
                    raise GoogleAPIError(401, "no refresh token")
                refreshed = self.client.refresh(refresh_token)
            except GoogleAPIError as exc:
                with self._lock:
                    self._connections.pop(self._key(connection), None)  # only this account; others keep working
                self._persist()
                email = connection.account.get("email") or "Google"
                raise ConnectorError(f"The session for {email} expired. Connect it again.", 409) from exc
            tokens.update({k: v for k, v in refreshed.items() if k != "refresh_token"})
            self._persist()
        return tokens["access_token"]

    def _require_scope(self, scope: str, label: str, account: str | None = None) -> None:
        connection = self._find(account) if self._connections else None
        granted = set((connection.tokens.get("scope") or "").split()) if connection else set()
        if scope not in granted:
            raise ConnectorError(f"{label} access was not granted. Disconnect and connect Google again.", 403)

    # --- data ---------------------------------------------------------------------------------

    def events(self, days_back: int, days_ahead: int, account: str | None = None) -> list[dict]:
        """Meet events on an account's primary calendar (the primary account by default)."""
        token = self._access_token(account)
        self._require_scope(REQUIRED_SCOPES[0], "Calendar", account)
        now = datetime.now(timezone.utc)
        payload = self._call(self.client.list_events, token, now - timedelta(days=days_back), now + timedelta(days=days_ahead))
        events = [simplify_event(e) for e in payload.get("items", []) if e.get("status") != "cancelled"]
        return [e for e in reversed(events) if e["meeting_code"]]  # Meet events, most recent first

    def conference_records(self, meeting_code: str, start: str | None, end: str | None) -> list[dict]:
        token = self._access_token()
        self._require_scope(REQUIRED_SCOPES[1], "Google Meet")
        try:
            window = conference_window(start, end)
        except ValueError as exc:
            raise ConnectorError("start and end must be RFC 3339 timestamps.", 422) from exc
        records = self._call(self.client.list_conference_records, token, meeting_code, *window)
        result = []
        for record in sorted(records, key=lambda r: r.get("startTime", ""), reverse=True):
            transcripts = self._call(self.client.list_transcripts, token, record["name"])
            result.append({
                "name": record["name"],
                "start_time": record.get("startTime"),
                "end_time": record.get("endTime"),
                "transcripts": [
                    {
                        "name": t["name"],
                        "state": t.get("state", "STATE_UNSPECIFIED"),
                        "docs_url": (t.get("docsDestination") or {}).get("exportUri"),
                    }
                    for t in transcripts
                ],
            })
        return result

    def transcript_segments(self, transcript_name: str) -> list[SegmentIn]:
        token = self._access_token()
        self._require_scope(REQUIRED_SCOPES[1], "Google Meet")
        record = transcript_name.split("/transcripts/")[0]
        entries = self._call(self.client.list_transcript_entries, token, transcript_name)
        participants = self._call(self.client.list_participants, token, record)
        speakers = {p["name"]: participant_display_name(p) for p in participants}
        return entries_to_segments(entries, speakers)

    @staticmethod
    def _call(method, *args):
        try:
            return method(*args)
        except GoogleAPIError as exc:
            status = exc.status_code if exc.status_code in (400, 403, 404, 429) else 502
            raise ConnectorError(f"Google API: {exc.message}", status) from exc
        except ValueError as exc:
            raise ConnectorError(str(exc), 422) from exc


    # --- auto-import: Workspace Events subscription + Pub/Sub pull --------------------------

    @property
    def connected(self) -> bool:
        return bool(self._connections)

    def auto_import_status(self) -> dict:
        settings = self.client.settings
        subscription = self._events_subscription or {}
        return {
            "configured": settings.auto_import_configured,
            "topic": settings.google_pubsub_topic or None,
            "subscription": settings.google_pubsub_subscription or None,
            "events_subscription": subscription.get("name"),
            "events_subscription_expires": subscription.get("expireTime"),
            "error": self.events_error,
        }

    def ensure_events_subscription(self) -> None:
        """Subscribe to 'transcript ready' events for the connected account; reuse or renew if it exists."""
        settings = self.client.settings
        connection = self._connection
        if not (settings.auto_import_configured and connection):
            return
        try:
            token = self._access_token()
            if PUBSUB_SCOPE not in set((connection.tokens.get("scope") or "").split()):
                raise ConnectorError("Pub/Sub access was not granted. Disconnect and connect Google again.", 403)
            if not connection.account_id:
                raise ConnectorError("Google did not return an account id.", 502)
            target = f"//cloudidentity.googleapis.com/users/{connection.account_id}"
            current = self._events_subscription
            if current is None:
                current = self.client.find_events_subscription(token, target)
            if current is None:
                try:
                    current = self.client.create_events_subscription(token, target, settings.google_pubsub_topic)
                except GoogleAPIError as exc:
                    if exc.status_code != 409:
                        raise
                    current = self.client.find_events_subscription(token, target)  # created earlier
            if current and _expires_within(current.get("expireTime"), hours=24):
                current = self.client.renew_events_subscription(token, current["name"]) or current
            self._events_subscription = current
            self.events_error = None if current else "Google did not return the event subscription."
        except ConnectorError as exc:
            self.events_error = str(exc)
        except GoogleAPIError as exc:
            self.events_error = f"Could not subscribe to Meet events: {exc.message}"
        except ValueError as exc:
            self.events_error = f"Could not subscribe to Meet events: {exc}"
        if self.events_error:
            logger.warning("Auto-import subscription problem: %s", self.events_error)

    def pull_transcript_events(self, max_messages: int = 10) -> list[TranscriptEvent]:
        token = self._access_token()
        subscription = self.client.settings.google_pubsub_subscription
        received = self._call(self.client.pubsub_pull, token, subscription, max_messages)
        events = []
        for item in received:
            message = item.get("message") or {}
            event_type = (message.get("attributes") or {}).get("ce-type", "")
            name = None
            if event_type == TRANSCRIPT_READY:
                try:
                    data = json.loads(b64decode(message.get("data") or "") or b"{}")
                    name = (data.get("transcript") or {}).get("name")
                except (ValueError, TypeError):
                    name = None
            events.append(TranscriptEvent(ack_id=item.get("ackId", ""), event_type=event_type, transcript_name=name))
        return events

    def ack(self, ack_ids: list[str]) -> None:
        if ack_ids:
            subscription = self.client.settings.google_pubsub_subscription
            self._call(self.client.pubsub_ack, self._access_token(), subscription, ack_ids)

    def transcript_meeting_info(self, transcript_name: str) -> dict:
        """Title, attendees and start time for a transcript, from its Calendar event when one matches."""
        token = self._access_token()
        record = self._call(self.client.get_resource, token, transcript_name.split("/transcripts/")[0])
        started = record.get("startTime")
        info = {"title": None, "participants": [], "occurred_at": started}
        try:
            space = self._call(self.client.get_resource, token, record.get("space", ""))
            code = space.get("meetingCode")
            if code and started:
                start = datetime.fromisoformat(started.replace("Z", "+00:00"))
                payload = self._call(self.client.list_events, token, start - timedelta(hours=12), start + timedelta(hours=12))
                for event in payload.get("items", []):
                    simple = simplify_event(event)
                    if simple["meeting_code"] == code:
                        info.update(title=simple["title"], participants=simple["attendees"])
                        break
        except ConnectorError as exc:
            logger.info("No calendar match for %s: %s", transcript_name, exc)
        if not info["title"]:
            info["title"] = f"Google Meet call ({started[:10] if started else 'unknown date'})"
        return info


def _expires_within(expire_time: str | None, hours: int) -> bool:
    if not expire_time:
        return False
    try:
        expires = datetime.fromisoformat(expire_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires - datetime.now(timezone.utc) < timedelta(hours=hours)
