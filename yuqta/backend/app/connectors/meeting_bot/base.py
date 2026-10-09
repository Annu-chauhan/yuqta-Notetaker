"""Meeting bot connector: a notetaker participant that joins a live call and returns its transcript.

The workflow (app/workflows/meeting_bot.py) only sees this interface, so Recall.ai and the mock are
interchangeable. Transcripts use Recall.ai's format (one entry per speaker turn, word-level timing).
"""

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal, Protocol

from app.schemas.transcript import SegmentIn


class BotError(Exception):
    """A provider call failed. `permanent` means retrying will not help (e.g. the bot no longer exists)."""

    def __init__(self, message: str, status_code: int = 502, permanent: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.permanent = permanent


TranscriptStatus = Literal["none", "processing", "done", "failed"]


@dataclass(frozen=True)
class BotState:
    code: str  # provider status: joining_call, in_waiting_room, in_call_recording, call_ended, done, fatal, ...
    sub_code: str | None = None
    message: str | None = None
    recorded: bool = False  # the bot produced a recording
    transcript_status: TranscriptStatus = "none"
    transcript_url: str | None = None


class MeetingBotClient(Protocol):
    name: str

    def create_bot(self, meeting_url: str, bot_name: str, join_at: datetime | None = None) -> str:
        """Sends a bot into the call now, or at join_at; returns the provider's bot id."""

    def delete_scheduled_bot(self, bot_id: str) -> None:
        """Cancels a bot that has not started joining yet."""

    def get_recording_url(self, bot_id: str) -> str | None:
        """A fresh, temporary link to the meeting video; None while it is not ready (or never recorded)."""

    def get_bot(self, bot_id: str) -> BotState: ...

    def leave_call(self, bot_id: str) -> None: ...

    def download_transcript(self, url: str) -> list[dict]: ...


# Links a bot can join. Google Meet codes are xxx-xxxx-xxx; Zoom and Teams links vary more.
MEETING_URL_PATTERN = re.compile(
    r"^https://(meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}"
    r"|([\w-]+\.)?zoom\.us/(j|my|w)/[\w.?=&-]+"
    r"|teams\.(microsoft|live)\.com/[\w%./?=&:@~+-]+)$"
)


def normalize_meeting_url(value: str) -> str | None:
    """Canonical join link, or None if it is not a supported meeting link. Accepts a link without https://."""
    url = value.strip()
    if not url.startswith(("https://", "http://")):
        url = f"https://{url}"
    url = url.replace("http://", "https://", 1)
    if url.startswith("https://meet.google.com/"):
        url = url.split("?", 1)[0].rstrip("/").lower()
    return url if MEETING_URL_PATTERN.match(url) and len(url) <= 500 else None


def parse_transcript(entries: list[dict]) -> tuple[list[SegmentIn], datetime | None]:
    """Recall.ai transcript JSON -> one segment per speaker turn, plus when the first word was spoken."""
    segments: list[SegmentIn] = []
    started_at: datetime | None = None
    for entry in entries:
        words = [w for w in entry.get("words") or [] if str(w.get("text", "")).strip()]
        if not words:
            continue
        participant = entry.get("participant") or {}
        start = (words[0].get("start_timestamp") or {})
        end = (words[-1].get("end_timestamp") or {})
        first_spoken = _parse_time(start.get("absolute"))
        if first_spoken and (started_at is None or first_spoken < started_at):
            started_at = first_spoken
        start_seconds = _seconds(start.get("relative"))
        end_seconds = _seconds(end.get("relative"))
        if start_seconds is not None and end_seconds is not None and end_seconds < start_seconds:
            end_seconds = start_seconds
        segments.append(
            SegmentIn(
                speaker=str(participant.get("name") or "Unknown speaker")[:200],
                text=" ".join(str(w["text"]).strip() for w in words)[:20_000],
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        )
    return segments, started_at


def _seconds(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
