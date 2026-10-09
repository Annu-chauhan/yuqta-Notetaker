from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.connectors.google import ConnectorError, GoogleConnector, get_google_connector
from app.connectors.google.client import MEETING_CODE_PATTERN, TRANSCRIPT_NAME_PATTERN
from app.db.session import get_db, get_session_factory
from app.plugins.llm.factory import build_llm_provider
from app.core.config import get_settings
from app.schemas.meeting import MeetingDetail
from app.workflows.auto_import import auto_importer
from app.workflows.ingest_meeting import IngestionError, ingest_from_segments


router = APIRouter(tags=["google"])


class ConnectRequest(BaseModel):
    return_path: str = Field(default="/import", max_length=200)


class ImportRequest(BaseModel):
    transcript_name: str = Field(pattern=TRANSCRIPT_NAME_PATTERN.pattern)
    title: str = Field(min_length=1, max_length=300)
    participants: list[str] = Field(default_factory=list, max_length=200)


def _fail(error: ConnectorError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=str(error))


@router.get("/api/google/status")
def google_status(connector: GoogleConnector = Depends(get_google_connector)) -> dict:
    return connector.status()


@router.post("/api/google/connect")
def google_connect(body: ConnectRequest, connector: GoogleConnector = Depends(get_google_connector)) -> dict:
    """Returns Google's sign-in URL. The browser goes there, then comes back via /auth/google/callback."""
    try:
        return {"authorization_url": connector.start_connect(body.return_path)}
    except ConnectorError as error:
        raise _fail(error) from error


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = Query(default=None, max_length=100),
    connector: GoogleConnector = Depends(get_google_connector),
) -> RedirectResponse:
    # Public: Google redirects the browser here. Only a state issued by /api/google/connect is accepted.
    return RedirectResponse(connector.complete_connect(code, state, error), status_code=status.HTTP_302_FOUND)


class DisconnectRequest(BaseModel):
    account: str | None = Field(default=None, max_length=320)  # an email; omitted = disconnect all accounts


@router.post("/api/google/disconnect")
def google_disconnect(
    body: DisconnectRequest | None = None, connector: GoogleConnector = Depends(get_google_connector)
) -> dict:
    try:
        connector.disconnect(body.account if body else None)
    except ConnectorError as error:
        raise _fail(error) from error
    return {"connected": connector.connected, "accounts": connector.accounts()}


@router.get("/api/google/events")
def google_events(
    days_back: int = Query(default=7, ge=0, le=90),
    days_ahead: int = Query(default=1, ge=0, le=90),
    connector: GoogleConnector = Depends(get_google_connector),
) -> dict:
    try:
        return {"events": connector.events(days_back, days_ahead)}
    except ConnectorError as error:
        raise _fail(error) from error


@router.get("/api/google/conference-records")
def google_conference_records(
    meeting_code: str = Query(pattern=MEETING_CODE_PATTERN.pattern),
    start: str | None = Query(default=None, max_length=40),
    end: str | None = Query(default=None, max_length=40),
    connector: GoogleConnector = Depends(get_google_connector),
) -> dict:
    try:
        return {"conference_records": connector.conference_records(meeting_code, start, end)}
    except ConnectorError as error:
        raise _fail(error) from error


@router.post("/api/google/import", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def google_import(
    body: ImportRequest,
    db: Session = Depends(get_db),
    connector: GoogleConnector = Depends(get_google_connector),
) -> MeetingDetail:
    """Imports a Meet transcript as a Yuqta meeting (source google_meet), ready to analyze."""
    from app.api.meetings import _detail

    try:
        segments = connector.transcript_segments(body.transcript_name)
    except ConnectorError as error:
        raise _fail(error) from error
    if not segments:
        raise HTTPException(
            status_code=404,
            detail="This transcript has no entries yet. Entries appear after transcription ends "
            "and are deleted 30 days after the meeting.",
        )
    try:
        meeting = ingest_from_segments(
            db, body.title.strip(), body.participants, segments, source="google_meet", external_ref=body.transcript_name
        )
    except IngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _detail(meeting)


# --- Auto-import ------------------------------------------------------------------------------


def _auto_status(connector: GoogleConnector) -> dict:
    return {
        "mode": connector.mode,
        "connected": connector.connected,
        "poll_seconds": connector.client.settings.auto_import_poll_seconds,
        **connector.auto_import_status(),
        **auto_importer.status(),
    }


@router.get("/api/google/auto-import")
def auto_import_status(connector: GoogleConnector = Depends(get_google_connector)) -> dict:
    return _auto_status(connector)


@router.post("/api/google/auto-import/run")
def auto_import_run(
    connector: GoogleConnector = Depends(get_google_connector),
    session_factory=Depends(get_session_factory),
) -> dict:
    """Check for finished meetings now instead of waiting for the next background poll."""
    auto_importer.run_once(connector, session_factory, lambda: build_llm_provider(get_settings()))
    return _auto_status(connector)


@router.post("/api/google/auto-import/simulate")
def auto_import_simulate(
    connector: GoogleConnector = Depends(get_google_connector),
    session_factory=Depends(get_session_factory),
) -> dict:
    """Mock mode only: pretend a Meet call just ended and Google published 'transcript ready'."""
    fake = getattr(connector.client, "fake", None)
    if connector.mode != "mock" or fake is None:
        raise HTTPException(status_code=404, detail="Simulation is only available with GOOGLE_MODE=mock.")
    if not connector.connected:
        raise HTTPException(status_code=409, detail="Connect Google (mock) first.")
    fake.simulate_transcript_ready()
    auto_importer.run_once(connector, session_factory, lambda: build_llm_provider(get_settings()))
    return _auto_status(connector)
