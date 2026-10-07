"""Deterministic meeting ingestion: create meeting -> transcribe -> normalise -> store.

This is a plain function on purpose. A future agent layer can decide *when* to call
it, but the steps themselves stay fixed and testable.
"""

from datetime import datetime
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import meetings as repo
from app.db.models import Meeting
from app.plugins.stt.base import STTError, STTProvider
from app.processing.transcript import normalize_segments, speakers
from app.schemas.transcript import AudioInput, SegmentIn


logger = logging.getLogger(__name__)


class IngestionError(Exception):
    def __init__(self, message: str, meeting_id: str | None = None):
        super().__init__(message)
        self.meeting_id = meeting_id


def _finish(db: Session, meeting: Meeting, segments: list[SegmentIn]) -> Meeting:
    cleaned = normalize_segments(segments)
    if not cleaned:
        raise IngestionError("Transcript has no spoken text.", str(meeting.id))
    repo.replace_segments(db, meeting, cleaned)
    if not meeting.participants:
        meeting.participants = speakers(cleaned)
    meeting.status = "transcribed"
    db.commit()
    logger.info("Meeting %s ingested (%s, %d segments)", meeting.id, meeting.source, len(cleaned))
    return meeting


def ingest_from_audio(
    db: Session,
    stt: STTProvider,
    title: str,
    participants: list[str],
    audio: AudioInput,
    occurred_at: datetime | None = None,
) -> Meeting:
    meeting = repo.create_meeting(db, title, participants, f"{stt.name}_stt", occurred_at)
    db.commit()  # the meeting exists even if transcription fails, so the failure is visible
    try:
        result = stt.transcribe(audio)
        return _finish(db, meeting, result.segments)
    except (STTError, IngestionError) as error:
        db.rollback()
        meeting.status = "failed"
        db.commit()
        logger.warning("Meeting %s ingestion failed: %s", meeting.id, error)
        raise IngestionError(str(error), str(meeting.id)) from error


def ingest_from_segments(
    db: Session,
    title: str,
    participants: list[str],
    segments: list[SegmentIn],
    source: str = "manual",
    occurred_at: datetime | None = None,
    external_ref: str | None = None,
) -> Meeting:
    """For transcripts that already exist as text (manual entry, Google Meet import).

    With external_ref, importing the same external transcript again returns the existing meeting.
    """
    if external_ref and (existing := repo.find_by_external_ref(db, external_ref)) is not None:
        return existing
    cleaned = normalize_segments(segments)
    if not cleaned:
        raise IngestionError("Transcript has no spoken text.")
    try:
        meeting = repo.create_meeting(db, title, participants, source, occurred_at, external_ref)
        return _finish(db, meeting, cleaned)
    except IntegrityError:
        # Another request imported the same external transcript at the same moment.
        db.rollback()
        existing = repo.find_by_external_ref(db, external_ref) if external_ref else None
        if existing is None:
            raise
        return existing
