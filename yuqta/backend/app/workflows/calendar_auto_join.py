"""Calendar auto-join: send the notetaker bot to every Google Meet on the connected calendar.

Every run reads the next AUTO_JOIN_HOURS_AHEAD hours of the calendar and, per Meet event:
- schedules a bot to join a minute before it starts (Recall.ai guarantees on-time joining for bots
  scheduled more than 10 minutes ahead), or sends one right away if the meeting has already started;
- reschedules the bot if the event moved, and cancels it if the event was deleted or declined.
Each calendar event gets at most one bot. Bots that already started joining are never touched.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google import ConnectorError, GoogleConnector
from app.connectors.meeting_bot.base import BotError, MeetingBotClient, normalize_meeting_url
from app.core.config import local_time
from app.db.models import MeetingBot
from app.workflows.meeting_bot import cancel_bot, send_bot


logger = logging.getLogger(__name__)

JOIN_EARLY = timedelta(minutes=1)
CHANGEABLE_BEFORE = timedelta(minutes=10)  # a scheduled bot can be moved or deleted until 10 min before it joins


@dataclass
class CalendarAutoJoiner:
    last_run_at: str | None = None
    last_error: str | None = None
    recent: list[str] = field(default_factory=list)  # what the last runs did, newest first
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def status(self) -> dict:
        return {"last_run_at": self.last_run_at, "last_error": self.last_error, "recent": self.recent[:10]}

    def run_once(
        self,
        connector: GoogleConnector,
        client: MeetingBotClient,
        session_factory: Callable[[], Session],
        bot_name: str,
        hours_ahead: int,
        now: datetime | None = None,
    ) -> list[str]:
        """One pass over the calendar. Returns what changed (also kept in `recent`). Thread-safe."""
        with self._lock:
            now = now or datetime.now(timezone.utc)
            self.last_run_at = now.isoformat(timespec="seconds")
            if not connector.connected:
                self.last_error = "Google Calendar is not connected."
                return []
            try:
                events = connector.events(0, max(1, -(-hours_ahead // 24)))
            except ConnectorError as error:
                if "Could not reach Google" in str(error):  # network/DNS blip: temporary, retried on the next run
                    self.last_error = "Could not reach Google (network problem). Yuqta retries automatically on the next check."
                else:
                    self.last_error = f"Could not read the calendar: {error}"
                logger.warning("Calendar auto-join: %s", error)
                return []
            self.last_error = None
            horizon = now + timedelta(hours=hours_ahead)
            wanted = {}
            for event in events:
                start, end = _time(event.get("start")), _time(event.get("end"))
                url = normalize_meeting_url(event.get("meet_link") or "") if event.get("meet_link") else None
                if (event.get("all_day") or event.get("declined") or not url or start is None
                        or start > horizon or (end is not None and end <= now)):
                    continue
                wanted[event["id"]] = (event, url, start)

            with session_factory() as db:
                changes = self._sync(db, client, wanted, bot_name, now, horizon)
            self.recent = (changes + self.recent)[:20]
            return changes

    def _sync(self, db: Session, client: MeetingBotClient, wanted: dict, bot_name: str, now: datetime, horizon: datetime) -> list[str]:
        changes: list[str] = []
        known = {
            bot.calendar_event_id: bot
            for bot in db.scalars(
                select(MeetingBot).where(MeetingBot.calendar_event_id.is_not(None)).order_by(MeetingBot.created_at)
            )
        }  # latest bot per event wins

        # Events that disappeared from the calendar (deleted, declined): cancel their scheduled bots.
        for event_id, bot in known.items():
            if event_id in wanted or bot.status != "scheduled" or bot.join_at is None:
                continue
            if _aware(bot.join_at) <= horizon and _aware(bot.join_at) - now > CHANGEABLE_BEFORE:
                if self._cancel(db, client, bot, "Cancelled: the meeting was removed from the calendar or declined."):
                    changes.append(f"Cancelled bot for “{bot.title}” (removed from calendar)")

        for event_id, (event, url, start) in wanted.items():
            join_at = start - JOIN_EARLY
            bot = known.get(event_id)
            title = event.get("title") or "Calendar meeting"
            if bot is not None:
                moved = bot.status == "scheduled" and bot.join_at is not None and _aware(bot.join_at) != join_at
                if not moved or _aware(bot.join_at) - now <= CHANGEABLE_BEFORE:
                    continue  # already handled; bots about to join or in the call are left alone
                if not self._cancel(db, client, bot, "Rescheduled: the meeting time changed."):
                    continue
            try:
                send_bot(db, client, url, title, bot_name, join_at=join_at, calendar_event_id=event_id)
            except BotError as error:
                logger.warning("Calendar auto-join could not schedule %s: %s", event_id, error)
                changes.append(f"Could not send the bot to “{title}”: {error}")
                continue
            when = "now (meeting already started)" if join_at <= now else f"at {local_time(join_at, '%d %b, %H:%M')}"
            changes.append(f"{'Rescheduled' if bot else 'Scheduled'} bot for “{title}”, joining {when}")
            logger.info("Calendar auto-join: bot for %s (%s) joining %s", event_id, title, when)
        return changes

    @staticmethod
    def _cancel(db: Session, client: MeetingBotClient, bot: MeetingBot, reason: str) -> bool:
        try:
            cancel_bot(db, client, bot, reason)
            return True
        except BotError as error:
            if error.status_code == 404:  # already gone at the provider
                bot.status, bot.detail = "cancelled", reason
                db.commit()
                return True
            logger.warning("Calendar auto-join could not cancel bot %s: %s", bot.id, error)
            return False


def _time(value: str | None) -> datetime | None:
    if not value or "T" not in value:
        return None  # all-day dates have no time
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


calendar_auto_joiner = CalendarAutoJoiner()
