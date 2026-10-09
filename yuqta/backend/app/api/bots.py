from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.connectors.meeting_bot import BotError, MeetingBotClient, get_meeting_bot_client, normalize_meeting_url
from app.core.config import Settings, get_settings
from app.db.models import MeetingBot
from app.db.session import get_db, get_session_factory
from app.plugins.llm.factory import build_llm_provider
from app.connectors.google import GoogleConnector, get_google_connector
from app.workflows.calendar_auto_join import calendar_auto_joiner
from app.workflows.meeting_bot import ACTIVE, cancel_bot, list_bots, meeting_bot_poller, send_bot


router = APIRouter(prefix="/api/bots", tags=["meeting bots"])


class SendBotRequest(BaseModel):
    meeting_url: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=300)


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    meeting_url: str
    title: str
    status: str
    provider_status: str | None
    detail: str
    meeting_id: UUID | None
    join_at: datetime | None
    calendar_event_id: str | None
    created_at: datetime
    updated_at: datetime


class BotList(BaseModel):
    provider: str
    bot_name: str
    poll_seconds: int
    last_poll_at: str | None
    bots: list[BotOut]


def _bot_list(db: Session, settings: Settings) -> BotList:
    return BotList(
        provider=settings.meeting_bot_provider,
        bot_name=settings.bot_name,
        poll_seconds=settings.bot_poll_seconds,
        last_poll_at=meeting_bot_poller.last_poll_at,
        bots=[BotOut.model_validate(bot) for bot in list_bots(db)],
    )


@router.get("", response_model=BotList)
def get_bots(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> BotList:
    return _bot_list(db, settings)


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
def create_bot(
    body: SendBotRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: MeetingBotClient = Depends(get_meeting_bot_client),
) -> BotOut:
    """Sends the notetaker into a live call. When the call ends it is transcribed, analyzed and put on the dashboard."""
    meeting_url = normalize_meeting_url(body.meeting_url)
    if meeting_url is None:
        raise HTTPException(status_code=422, detail="Paste a Google Meet, Zoom or Microsoft Teams meeting link.")
    title = " ".join(body.title.split()) or "Live meeting"
    try:
        bot = send_bot(db, client, meeting_url, title, settings.bot_name)
    except BotError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return BotOut.model_validate(bot)


@router.post("/check", response_model=BotList)
def check_bots(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: MeetingBotClient = Depends(get_meeting_bot_client),
    session_factory=Depends(get_session_factory),
) -> BotList:
    """Checks the active bots now instead of waiting for the next background poll."""
    meeting_bot_poller.run_once(client, session_factory, lambda: build_llm_provider(get_settings()))
    db.expire_all()
    return _bot_list(db, settings)


@router.post("/{bot_id}/leave", response_model=BotOut)
def leave_call(bot_id: UUID, db: Session = Depends(get_db), client: MeetingBotClient = Depends(get_meeting_bot_client)) -> BotOut:
    """Asks the bot to leave now. What it recorded so far is still transcribed and analyzed."""
    bot = db.get(MeetingBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.provider != client.name:
        raise HTTPException(status_code=409, detail=f"This bot was sent with the {bot.provider} provider.")
    if bot.status == "scheduled":
        try:
            cancel_bot(db, client, bot, "Cancelled before the meeting.")
        except BotError as error:
            raise HTTPException(status_code=409 if error.status_code == 400 else error.status_code, detail=str(error)) from error
        return BotOut.model_validate(bot)
    if bot.status not in ACTIVE or bot.status == "processing":
        raise HTTPException(status_code=409, detail="The bot is no longer in the call.")
    try:
        client.leave_call(bot.external_id)
    except BotError as error:
        # 400 = the bot has already left (e.g. a double click); its status catches up on the next check.
        if error.status_code != 400:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    bot.detail = "Leaving the call…"
    db.commit()
    return BotOut.model_validate(bot)



@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bot(bot_id: UUID, db: Session = Depends(get_db)) -> None:
    """Removes a finished or failed bot from the list, together with the meeting it produced (if any)."""
    from app.db import meetings as meetings_repo

    bot = db.get(MeetingBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.status in ACTIVE:
        action = "Cancel it" if bot.status == "scheduled" else "End the recording"
        raise HTTPException(status_code=409, detail=f"The bot is still active. {action} first.")
    meeting_id = bot.meeting_id
    db.delete(bot)
    db.commit()
    if meeting_id is not None:
        meetings_repo.delete_meeting(db, meeting_id)

# --- Calendar auto-join ---------------------------------------------------------------------


def _auto_join_status(settings: Settings, connector: GoogleConnector) -> dict:
    return {
        "enabled": settings.auto_join_calendar,
        "google_mode": connector.mode,
        "google_connected": connector.connected,
        "hours_ahead": settings.auto_join_hours_ahead,
        "poll_seconds": settings.auto_join_poll_seconds,
        **calendar_auto_joiner.status(),
    }


@router.get("/calendar")
def calendar_auto_join_status(
    settings: Settings = Depends(get_settings), connector: GoogleConnector = Depends(get_google_connector)
) -> dict:
    return _auto_join_status(settings, connector)


@router.post("/calendar/sync")
def calendar_auto_join_sync(
    settings: Settings = Depends(get_settings),
    connector: GoogleConnector = Depends(get_google_connector),
    client: MeetingBotClient = Depends(get_meeting_bot_client),
    session_factory=Depends(get_session_factory),
) -> dict:
    """Reads the calendar now and schedules/reschedules/cancels bots, instead of waiting for the next run."""
    if not settings.auto_join_calendar:
        raise HTTPException(status_code=409, detail="Calendar auto-join is off. Set AUTO_JOIN_CALENDAR=true.")
    calendar_auto_joiner.run_once(connector, client, session_factory, settings.bot_name, settings.auto_join_hours_ahead)
    return _auto_join_status(settings, connector)
