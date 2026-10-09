"""Persistence for meetings and their transcript segments."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.db.models import Meeting, MeetingBot, TranscriptSegment
from app.schemas.transcript import SegmentIn


def create_meeting(
    db: Session,
    title: str,
    participants: list[str],
    source: str,
    occurred_at: datetime | None,
    external_ref: str | None = None,
) -> Meeting:
    meeting = Meeting(
        title=title, participants=participants, source=source, status="created", occurred_at=occurred_at, external_ref=external_ref
    )
    db.add(meeting)
    db.flush()
    return meeting


def replace_segments(db: Session, meeting: Meeting, segments: list[SegmentIn]) -> None:
    meeting.segments = [
        TranscriptSegment(
            segment_index=index,
            speaker=segment.speaker,
            text=segment.text,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
        )
        for index, segment in enumerate(segments)
    ]
    db.flush()


def get_meeting(db: Session, meeting_id: UUID) -> Meeting | None:
    return db.scalars(
        select(Meeting).where(Meeting.id == meeting_id).options(selectinload(Meeting.segments))
    ).one_or_none()


def list_meetings(db: Session, limit: int = 50) -> list[tuple[Meeting, int]]:
    segment_count = (
        select(func.count(TranscriptSegment.id))
        .where(TranscriptSegment.meeting_id == Meeting.id)
        .correlate(Meeting)
        .scalar_subquery()
    )
    rows = db.execute(select(Meeting, segment_count).order_by(Meeting.created_at.desc()).limit(limit))
    return [(meeting, count) for meeting, count in rows]


def find_by_external_ref(db: Session, external_ref: str) -> Meeting | None:
    return db.scalars(
        select(Meeting).where(Meeting.external_ref == external_ref).options(selectinload(Meeting.segments))
    ).one_or_none()


def delete_meeting(db: Session, meeting_id: UUID) -> bool:
    """Deletes a meeting with its transcript, analysis and dashboard. Returns False if it did not exist.

    A bot that recorded the meeting keeps its row (the call happened) but no longer links to it.
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        return False
    db.execute(
        update(MeetingBot).where(MeetingBot.meeting_id == meeting_id).values(meeting_id=None, detail="The meeting was deleted.")
    )
    db.delete(meeting)  # segments and insights via the ORM; the dashboard via ON DELETE CASCADE
    db.commit()
    return True
