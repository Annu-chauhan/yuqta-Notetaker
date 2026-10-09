from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.mailer import mail_configured
from app.connectors.meeting_bot import BotError, MeetingBotClient, get_meeting_bot_client
from app.db.models import Meeting, MeetingBot, MinutesEmail
from app.db.session import get_db
from app.workflows.minutes import (
    MinutesError,
    admin_for,
    build_minutes,
    external_recipients,
    send_minutes,
    suggested_recipients,
)


router = APIRouter(prefix="/api/meetings", tags=["minutes"])


class MinutesStatus(BaseModel):
    mode: Literal["off", "review", "auto"]
    mail_configured: bool
    status: Literal["not_sent", "awaiting_approval", "sent", "failed", "skipped"]
    detail: str
    recipients: list[str]  # who it went / will go to
    external: list[str]  # of those, the ones outside the organisation
    subject: str | None
    sent_at: datetime | None
    preview_html: str | None  # None until the meeting is analyzed
    admin_email: str | None  # gets a separate copy with the recording link
    admin_sent_at: datetime | None
    admin_detail: str


class SendRequest(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=100)


def _status(db: Session, settings: Settings, meeting_id: UUID) -> MinutesStatus:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    row = db.get(MinutesEmail, meeting_id)
    recipients = row.recipients if row and row.recipients else suggested_recipients(db, settings, meeting_id)
    try:
        minutes = build_minutes(db, settings, meeting)
    except MinutesError:
        minutes = None
    return MinutesStatus(
        mode=settings.minutes_email,
        mail_configured=mail_configured(settings),
        status=row.status if row else "not_sent",
        detail=row.detail if row else "",
        recipients=recipients,
        external=external_recipients(settings, recipients),
        subject=(row.subject if row and row.subject else None) or (minutes.subject if minutes else None),
        sent_at=row.sent_at if row else None,
        preview_html=minutes.html if minutes else None,
        admin_email=(row.admin_email if row and row.admin_email else None) or admin_for(db, settings, meeting_id),
        admin_sent_at=row.admin_sent_at if row else None,
        admin_detail=row.admin_detail if row else "",
    )


@router.get("/{meeting_id}/minutes", response_model=MinutesStatus)
def get_minutes(meeting_id: UUID, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> MinutesStatus:
    return _status(db, settings, meeting_id)


@router.post("/{meeting_id}/minutes/send", response_model=MinutesStatus)
def post_minutes(
    meeting_id: UUID,
    body: SendRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: MeetingBotClient = Depends(get_meeting_bot_client),
) -> MinutesStatus:
    """Sends the minutes to the given addresses (approving a held email, or sending by hand)."""
    try:
        send_minutes(db, settings, meeting_id, body.recipients, recording_url=lambda: _recording_link(db, client, meeting_id))
    except MinutesError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return _status(db, settings, meeting_id)


def _recording_link(db: Session, client: MeetingBotClient, meeting_id: UUID) -> str | None:
    bot = db.scalars(
        select(MeetingBot)
        .where(MeetingBot.meeting_id == meeting_id, MeetingBot.provider == client.name)
        .order_by(MeetingBot.created_at.desc())
    ).first()
    return client.get_recording_url(bot.external_id) if bot else None


class RecordingLink(BaseModel):
    url: str
    expires_in_hours: int = 6


@router.get("/{meeting_id}/recording", response_model=RecordingLink)
def get_recording(
    meeting_id: UUID, db: Session = Depends(get_db), client: MeetingBotClient = Depends(get_meeting_bot_client)
) -> RecordingLink:
    """A fresh link to the meeting video (signed by the recording provider, valid for about 6 hours)."""
    if db.get(Meeting, meeting_id) is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        url = _recording_link(db, client, meeting_id)
    except BotError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if not url:
        raise HTTPException(
            status_code=404,
            detail="No recording for this meeting: it was not recorded by the Yuqta bot, or the video is still processing.",
        )
    return RecordingLink(url=url)
