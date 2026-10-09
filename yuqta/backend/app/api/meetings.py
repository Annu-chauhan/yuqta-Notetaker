from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.db import meetings as repo
from app.db.models import Meeting
from app.db.session import get_db
from app.plugins.llm import LLMProvider, get_llm_provider
from app.core.config import get_settings
from app.plugins.stt import STTProvider, get_sample_stt_provider, get_stt_provider
from app.schemas.analysis import AnalysisResult
from app.schemas.dashboard import DashboardSpec
from app.schemas.meeting import MeetingCreate, MeetingDetail, MeetingSummary
from app.schemas.transcript import AudioInput
from app.workflows.analyze_meeting import AnalysisError, analyze_meeting, load_analysis, load_dashboard
from app.workflows.edit_analysis import EditError, ItemKind, remove_item
from app.workflows.ingest_meeting import IngestionError, ingest_from_audio, ingest_from_segments


router = APIRouter(prefix="/api/meetings", tags=["meetings"])
SAMPLE_TITLE = "Enterprise Revenue Review"
SAMPLE_PARTICIPANTS = ["Sales Manager", "Finance Manager", "Product Manager"]


def _detail(meeting: Meeting) -> MeetingDetail:
    detail = MeetingDetail.model_validate(meeting)
    detail.segment_count = len(detail.segments)
    return detail


@router.get("", response_model=list[MeetingSummary])
def list_meetings(db: Session = Depends(get_db)) -> list[MeetingSummary]:
    return [
        MeetingSummary.model_validate(meeting).model_copy(update={"segment_count": count})
        for meeting, count in repo.list_meetings(db)
    ]


@router.post("/sample", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def create_sample_meeting(
    db: Session = Depends(get_db),
    stt: STTProvider = Depends(get_sample_stt_provider),
) -> MeetingDetail:
    """Creates the 'Enterprise Revenue Review' demo meeting from the fixture transcript (mock STT)."""
    try:
        meeting = ingest_from_audio(
            db, stt, SAMPLE_TITLE, SAMPLE_PARTICIPANTS, AudioInput(source_uri="sample://enterprise-revenue-review")
        )
    except IngestionError as error:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {error}") from error
    return _detail(meeting)


_CHUNK = 1024 * 1024


def _read_upload(upload: UploadFile, limit_mb: int) -> bytes:
    limit = limit_mb * 1024 * 1024
    data = bytearray()
    while chunk := upload.file.read(_CHUNK):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=f"Audio file is larger than {limit_mb} MB.")
    return bytes(data)


@router.post("/audio", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def create_meeting_from_audio(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    participants: str = Form(default="", max_length=2000),
    db: Session = Depends(get_db),
    stt: STTProvider = Depends(get_stt_provider),
) -> MeetingDetail:
    """Upload a recording; the configured STT provider (Deepgram, or the mock) transcribes it."""
    mime_type = (file.content_type or "").lower()
    if not mime_type.startswith(("audio/", "video/")):
        raise HTTPException(status_code=415, detail="Upload an audio or video file.")
    data = _read_upload(file, get_settings().max_audio_mb)
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    names = [name.strip() for name in participants.split(",") if name.strip()]
    try:
        meeting = ingest_from_audio(
            db, stt, title.strip(), names, AudioInput(data=data, mime_type=mime_type, source_uri=f"upload://{file.filename}")
        )
    except IngestionError as error:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {error}") from error
    return _detail(meeting)


@router.post("", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def create_meeting(submission: MeetingCreate, db: Session = Depends(get_db)) -> MeetingDetail:
    try:
        meeting = ingest_from_segments(
            db, submission.title.strip(), submission.participants, submission.segments, occurred_at=submission.occurred_at
        )
    except IngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _detail(meeting)


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: UUID, db: Session = Depends(get_db)) -> MeetingDetail:
    meeting = repo.get_meeting(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _detail(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: UUID, db: Session = Depends(get_db)) -> None:
    """Deletes the meeting, its transcript, analysis and dashboard. Cannot be undone."""
    if not repo.delete_meeting(db, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")


@router.delete("/{meeting_id}/items/{kind}/{index}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    meeting_id: UUID,
    kind: ItemKind,
    index: int,
    text: str = Query(min_length=1, max_length=2000),
    db: Session = Depends(get_db),
) -> None:
    """Removes one task, decision, risk or open question from the meeting's analysis and dashboard."""
    try:
        remove_item(db, meeting_id, kind, index, text)
    except EditError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/{meeting_id}/analyze", response_model=AnalysisResult)
def analyze(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> AnalysisResult:
    """Understand -> correlate with business data -> KPIs -> root cause. Replaces any earlier analysis."""
    try:
        return analyze_meeting(db, llm, meeting_id)
    except AnalysisError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/{meeting_id}/analysis", response_model=AnalysisResult)
def get_analysis(meeting_id: UUID, db: Session = Depends(get_db)) -> AnalysisResult:
    try:
        result = load_analysis(db, meeting_id)
    except AnalysisError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Meeting has not been analyzed yet")
    return result


@router.get("/{meeting_id}/dashboard", response_model=DashboardSpec)
def get_meeting_dashboard(meeting_id: UUID, db: Session = Depends(get_db)) -> DashboardSpec:
    spec = load_dashboard(db, meeting_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="No dashboard yet. Analyze the meeting first.")
    return spec
