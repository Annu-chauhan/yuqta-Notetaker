"""Live meetings: send a notetaker bot into a call, follow it, and analyze the call when it ends.

send_bot()      -> the provider's bot joins the call (the host admits it like any guest).
MeetingBotPoller.run_once() -> for every bot still active: read its status; once the call is over and the
                   transcript is ready, import it as a meeting (named speakers), analyze it and update the
                   dashboard. Polling (not webhooks) means Yuqta needs no public URL.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import threading
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.meeting_bot.base import BotError, BotState, MeetingBotClient, parse_transcript
from app.core.config import get_settings, local_time
from app.db.models import MeetingBot
from app.plugins.llm.base import LLMProvider
from app.workflows.analyze_meeting import analyze_meeting
from app.workflows.ingest_meeting import IngestionError, ingest_from_segments


logger = logging.getLogger(__name__)

ACTIVE = ("scheduled", "joining", "waiting", "in_call", "recording", "processing")

# Provider status -> Yuqta bot status, while the call is going on.
_LIVE_STATUS = {
    "ready": "joining",
    "joining_call": "joining",
    "in_waiting_room": "waiting",
    "in_call_not_recording": "in_call",
    "recording_permission_allowed": "in_call",
    "recording_permission_denied": "in_call",
    "in_call_recording": "recording",
    "call_ended": "processing",
}

_LIVE_DETAIL = {
    "joining": "Joining the call…",
    "waiting": "Waiting to be let in. Admit the bot in the meeting.",
    "in_call": "In the call, not recording yet.",
    "recording": "In the call and recording.",
    "processing": "The call has ended. Waiting for the transcript…",
}

_FATAL_DETAIL = {
    "bot_kicked_from_waiting_room": "The bot was not let into the call.",
    "timeout_exceeded_waiting_room": "Nobody let the bot into the call in time.",
    "timeout_exceeded_noone_joined": "Nobody joined the call.",
    "meeting_not_found": "The meeting link does not exist.",
    "meeting_not_started": "The meeting has not started.",
    "meeting_requires_sign_in": "The meeting only allows signed-in users.",
    "google_meet_sign_in_failed": "The meeting only allows signed-in users.",
    "meeting_link_expired": "The meeting link has expired.",
    "meeting_full": "The meeting is full.",
    "recording_permission_denied": "The host did not allow recording.",
}


def send_bot(
    db: Session,
    client: MeetingBotClient,
    meeting_url: str,
    title: str,
    bot_name: str,
    join_at: datetime | None = None,
    calendar_event_id: str | None = None,
    attendee_emails: list[str] | None = None,
    admin_email: str | None = None,
) -> MeetingBot:
    """Sends the bot now, or schedules it for join_at (a time in the future)."""
    scheduled = join_at is not None and join_at > datetime.now(timezone.utc)
    external_id = client.create_bot(meeting_url, bot_name, join_at if scheduled else None)
    bot = MeetingBot(
        provider=client.name,
        external_id=external_id,
        meeting_url=meeting_url,
        title=title,
        status="scheduled" if scheduled else "joining",
        provider_status=None if scheduled else "joining_call",
        detail=_scheduled_detail(join_at) if scheduled else _LIVE_DETAIL["joining"],
        join_at=join_at if scheduled else None,
        calendar_event_id=calendar_event_id,
        attendee_emails=attendee_emails or None,
        admin_email=(admin_email or "").strip().lower() or None,
    )
    db.add(bot)
    db.commit()
    logger.info("Bot %s (%s %s) sent to %s", bot.id, client.name, external_id, meeting_url)
    return bot


def cancel_bot(db: Session, client: MeetingBotClient, bot: MeetingBot, reason: str) -> None:
    """Cancels a scheduled bot before it joins (raises BotError if it already started joining)."""
    client.delete_scheduled_bot(bot.external_id)
    _set(bot, "cancelled", reason)
    db.commit()


def _scheduled_detail(join_at: datetime) -> str:
    return f"Scheduled: joins at {local_time(join_at, '%d %b %Y, %H:%M')}."


def list_bots(db: Session, limit: int = 20) -> list[MeetingBot]:
    return list(db.scalars(select(MeetingBot).order_by(MeetingBot.created_at.desc(), MeetingBot.id).limit(limit)))


class MeetingBotPoller:
    def __init__(self) -> None:
        self.last_poll_at: str | None = None
        self._lock = threading.Lock()

    def run_once(
        self,
        client: MeetingBotClient,
        session_factory: Callable[[], Session],
        llm_factory: Callable[[], LLMProvider],
    ) -> int:
        """Advances every active bot of this provider. Returns how many were checked. Thread-safe."""
        with self._lock, session_factory() as db:
            self.last_poll_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            ids = list(
                db.scalars(select(MeetingBot.id).where(MeetingBot.provider == client.name, MeetingBot.status.in_(ACTIVE)))
            )
            for bot_id in ids:
                try:
                    refresh_bot(db, client, bot_id, llm_factory)
                except Exception:  # noqa: BLE001 - one bad bot must not stop the others
                    db.rollback()
                    logger.exception("Checking bot %s failed", bot_id)
            return len(ids)


def refresh_bot(db: Session, client: MeetingBotClient, bot_id: UUID, llm_factory: Callable[[], LLMProvider]) -> MeetingBot:
    bot = db.get(MeetingBot, bot_id)
    if bot is None or bot.status not in ACTIVE:
        return bot
    try:
        state = client.get_bot(bot.external_id)
    except BotError as error:
        if error.permanent:
            _set(bot, "failed", str(error))
        else:
            bot.detail = f"Could not check the bot: {error}"  # transient: try again next poll
        db.commit()
        return bot

    bot.provider_status = state.code[:60]
    if bot.status == "scheduled" and state.code in ("scheduled", "ready", "unknown"):
        pass  # still waiting for its join time
    elif state.code == "fatal":
        _set(bot, "failed", _FATAL_DETAIL.get(state.sub_code or "", state.message or "The bot stopped with an error."))
    elif state.code == "done" or (state.code == "call_ended" and state.transcript_status == "done"):
        _finish(db, client, bot, state, llm_factory)
        return bot
    elif state.code in _LIVE_STATUS:
        status = _LIVE_STATUS[state.code]
        detail = _LIVE_DETAIL[status]
        if state.code == "recording_permission_denied":
            detail = "The host did not allow recording."
        _set(bot, status, detail)
    db.commit()
    return bot


def _finish(db: Session, client: MeetingBotClient, bot: MeetingBot, state: BotState, llm_factory) -> None:
    """The bot has left. Import its transcript, then analyze it."""
    if not state.recorded:
        _set(bot, "failed", _FATAL_DETAIL.get(state.sub_code or "", "The bot left without recording. Was it let into the call?"))
        db.commit()
        return
    if state.transcript_status == "failed":
        _set(bot, "failed", "Transcription of the recording failed.")
        db.commit()
        return
    if state.transcript_status != "done" or not state.transcript_url:
        _set(bot, "processing", "The call has ended. Transcribing the recording…")
        db.commit()
        return

    try:
        segments, started_at = parse_transcript(client.download_transcript(state.transcript_url))
    except BotError as error:
        bot.detail = f"Could not fetch the transcript yet: {error}"  # transient: retried next poll
        db.commit()
        return
    if not segments:
        _set(bot, "failed", "Nobody spoke while the bot was recording.")
        db.commit()
        return

    try:
        meeting = ingest_from_segments(
            db, bot.title, [], segments,
            source=f"{bot.provider}_bot", occurred_at=started_at or bot.created_at,
            external_ref=f"{bot.provider}_bot:{bot.external_id}",
        )
    except IngestionError as error:
        db.rollback()
        _set(bot, "failed", str(error))
        db.commit()
        return
    bot.meeting_id = meeting.id
    _set(bot, "transcribed", f"Transcribed: {len(meeting.segments)} turns from {len(meeting.participants)} speakers. Analyzing…")
    db.commit()

    try:
        analyze_meeting(db, llm_factory(), meeting.id)
    except Exception as error:  # noqa: BLE001 - keep the transcript even if analysis fails; record why
        db.rollback()
        reason = getattr(error, "detail", None) or str(error)
        logger.warning("Analysis of bot meeting %s failed: %s", meeting.id, reason)
        _set(bot, "transcribed", f"Transcribed, but analysis failed: {reason}. Open the meeting to retry.")
        db.commit()
        return
    _set(bot, "analyzed", "Transcribed and analyzed. The dashboard is updated.")
    db.commit()
    logger.info("Bot %s: meeting %s transcribed and analyzed", bot.id, meeting.id)
    try:
        from app.workflows.minutes import after_analysis

        after_analysis(db, get_settings(), meeting.id, recording_url=lambda: client.get_recording_url(bot.external_id))
    except Exception:  # noqa: BLE001 - the meeting is done; an email problem is logged, never fatal
        db.rollback()
        logger.exception("Minutes email for meeting %s failed", meeting.id)


def _set(bot: MeetingBot, status: str, detail: str) -> None:
    bot.status = status
    bot.detail = detail[:2000]


meeting_bot_poller = MeetingBotPoller()
