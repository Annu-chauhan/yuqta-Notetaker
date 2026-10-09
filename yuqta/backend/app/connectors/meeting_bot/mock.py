"""A simulated notetaker bot, for demos and tests without a Recall.ai key.

The bot's id encodes when it was sent, and its status follows a fixed timeline from then:
joining -> waiting room -> recording -> call ended -> done (transcript ready). It needs no stored
state, so a bot still "in the call" survives a backend restart. The transcript is the sample meeting
(data/sample_transcript.json) in Recall.ai's format, so the real parser is exercised too.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import time

from app.connectors.meeting_bot.base import BotError, BotState


# Seconds after the bot is sent at which each status starts.
TIMELINE: list[tuple[float, str]] = [
    (0, "joining_call"),
    (4, "in_waiting_room"),
    (8, "in_call_recording"),
    (24, "call_ended"),
    (28, "done"),
]
_ENDED_TO_DONE = TIMELINE[-1][0] - TIMELINE[-2][0]


class MockMeetingBotClient:
    name = "mock"

    def __init__(self, sample_transcript_path: str, clock: Callable[[], float] = time.time):
        self._sample_path = sample_transcript_path
        self._clock = clock
        self._left: dict[str, float] = {}  # bot id -> when it was told to leave
        self._deleted: set[str] = set()

    def create_bot(self, meeting_url: str, bot_name: str, join_at: datetime | None = None) -> str:
        # The id encodes when the bot joins: now, or the scheduled time.
        start = join_at.timestamp() if join_at is not None else self._clock()
        return f"mock-{int(start * 1000)}-{secrets.token_hex(4)}"

    def get_recording_url(self, bot_id: str) -> str | None:
        return None  # the simulated bot records no video

    def delete_scheduled_bot(self, bot_id: str) -> None:
        if self._clock() >= self._sent_at(bot_id):
            raise BotError("The bot has already started joining.", status_code=400, permanent=True)
        self._deleted.add(bot_id)

    def get_bot(self, bot_id: str) -> BotState:
        sent = self._sent_at(bot_id)
        if bot_id in self._deleted:
            raise BotError("No such mock bot.", status_code=404, permanent=True)
        elapsed = self._clock() - sent
        if elapsed < 0:
            return BotState(code="scheduled")  # waiting for its join time
        left = self._left.get(bot_id)
        if left is not None and left - sent < TIMELINE[-2][0]:
            # Told to leave early: the call ends then, and the transcript follows shortly after.
            if self._clock() - left < _ENDED_TO_DONE:
                code = "call_ended"
            else:
                code = "done"
            recorded = left - sent >= TIMELINE[2][0]
        else:
            code = next(status for start, status in reversed(TIMELINE) if elapsed >= start)
            recorded = elapsed >= TIMELINE[2][0]
        sub_code = "call_ended_by_host" if code in ("call_ended", "done") else None
        if code == "done" and not recorded:
            return BotState(code="done", sub_code="bot_kicked_from_waiting_room", recorded=False)
        return BotState(
            code=code,
            sub_code=sub_code,
            recorded=recorded,
            transcript_status="done" if code == "done" else ("processing" if recorded else "none"),
            transcript_url=f"mock://transcripts/{bot_id}" if code == "done" else None,
        )

    def leave_call(self, bot_id: str) -> None:
        self._sent_at(bot_id)
        self._left.setdefault(bot_id, self._clock())

    def download_transcript(self, url: str) -> list[dict]:
        bot_id = url.removeprefix("mock://transcripts/")
        sent = datetime.fromtimestamp(self._sent_at(bot_id), timezone.utc) + timedelta(seconds=TIMELINE[2][0])
        sample = json.loads(Path(self._sample_path).read_text(encoding="utf-8"))
        names = list(dict.fromkeys(s["speaker"] for s in sample["segments"]))
        entries = []
        for segment in sample["segments"]:
            words = segment["text"].split()
            start, end = float(segment["start_seconds"]), float(segment["end_seconds"])
            step = (end - start) / max(len(words), 1)
            entries.append(
                {
                    "participant": {"id": names.index(segment["speaker"]) + 1, "name": segment["speaker"], "platform": "google_meet"},
                    "words": [
                        {
                            "text": word,
                            "start_timestamp": {"relative": round(start + i * step, 2), "absolute": _iso(sent, start + i * step)},
                            "end_timestamp": {"relative": round(start + (i + 1) * step, 2), "absolute": _iso(sent, start + (i + 1) * step)},
                        }
                        for i, word in enumerate(words)
                    ],
                }
            )
        return entries

    @staticmethod
    def _sent_at(bot_id: str) -> float:
        try:
            prefix, millis, _ = bot_id.split("-", 2)
            if prefix != "mock":
                raise ValueError
            return int(millis) / 1000
        except ValueError as error:
            raise BotError("No such mock bot.", status_code=404, permanent=True) from error


def _iso(base: datetime, offset: float) -> str:
    return (base + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
