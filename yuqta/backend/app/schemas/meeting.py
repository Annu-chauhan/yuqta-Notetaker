from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.transcript import SegmentIn


class MeetingCreate(BaseModel):
    """A meeting whose transcript text is already known (manual entry or a connector import)."""

    title: str = Field(min_length=1, max_length=300)
    participants: list[str] = Field(default_factory=list, max_length=100)
    occurred_at: datetime | None = None
    segments: list[SegmentIn] = Field(min_length=1, max_length=5000)


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    segment_index: int
    speaker: str
    text: str
    start_seconds: float | None
    end_seconds: float | None


class MeetingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    participants: list[str]
    source: str
    status: str
    occurred_at: datetime | None
    created_at: datetime
    segment_count: int = 0


class MeetingDetail(MeetingSummary):
    segments: list[SegmentOut]
