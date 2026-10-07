"""Automatic import of finished Google Meet meetings.

Google publishes a "transcript ready" event to Pub/Sub when a meeting's transcript is generated.
This workflow pulls those events, imports each transcript as a meeting, analyzes it, and only then
acknowledges the event. Pub/Sub delivers at least once, so imports are idempotent (external_ref).
"""

from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import threading

from sqlalchemy.orm import Session

from app.connectors.google import ConnectorError, GoogleConnector
from app.db import meetings as repo
from app.plugins.llm.base import LLMProvider
from app.workflows.analyze_meeting import analyze_meeting
from app.workflows.ingest_meeting import IngestionError, ingest_from_segments


logger = logging.getLogger(__name__)


@dataclass
class Activity:
    at: str
    transcript: str | None
    status: str  # analyzed | imported | duplicate | skipped | failed
    detail: str = ""
    meeting_id: str | None = None
    title: str | None = None


@dataclass
class AutoImporter:
    activity: deque = field(default_factory=lambda: deque(maxlen=20))
    last_poll_at: str | None = None
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def status(self) -> dict:
        return {
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "recent": [asdict(item) for item in reversed(self.activity)],
        }

    def run_once(
        self,
        connector: GoogleConnector,
        session_factory: Callable[[], Session],
        llm_factory: Callable[[], LLMProvider],
    ) -> list[Activity]:
        """One poll: pull pending events and process them. Safe to call from several threads."""
        with self._lock:
            self.last_poll_at = _now()
            if not connector.client.settings.auto_import_configured:
                self.last_error = "Auto-import is not configured."
                return []
            if not connector.connected:
                self.last_error = "Google is not connected."
                return []
            connector.ensure_events_subscription()
            try:
                events = connector.pull_transcript_events()
            except ConnectorError as error:
                self.last_error = f"Could not read events: {error}"
                logger.warning("Auto-import pull failed: %s", error)
                return []
            self.last_error = connector.events_error

            results: list[Activity] = []
            for event in events:
                if not event.transcript_name:
                    connector.ack([event.ack_id])  # not a transcript event (or unreadable): nothing to do
                    continue
                result = self._process(connector, event.transcript_name, session_factory, llm_factory)
                if result.status != "failed":
                    connector.ack([event.ack_id])  # failed = transient; leave it for redelivery
                self.activity.append(result)
                results.append(result)
            return results

    def _process(self, connector: GoogleConnector, transcript: str, session_factory, llm_factory) -> Activity:
        with session_factory() as db:
            existing = repo.find_by_external_ref(db, transcript)
            if existing is not None:
                return Activity(_now(), transcript, "duplicate", "Already imported.", str(existing.id), existing.title)
            try:
                info = connector.transcript_meeting_info(transcript)
                segments = connector.transcript_segments(transcript)
            except ConnectorError as error:
                logger.warning("Auto-import of %s failed: %s", transcript, error)
                return Activity(_now(), transcript, "failed", str(error))
            if not segments:
                return Activity(_now(), transcript, "skipped", "The transcript has no entries.")
            try:
                meeting = ingest_from_segments(
                    db, info["title"], info["participants"], segments,
                    source="google_meet", occurred_at=_parse(info["occurred_at"]), external_ref=transcript,
                )
            except IngestionError as error:
                return Activity(_now(), transcript, "skipped", str(error))

            try:
                analyze_meeting(db, llm_factory(), meeting.id)
            except Exception as error:  # noqa: BLE001 - keep the import even if analysis fails; record why
                db.rollback()
                detail = getattr(error, "detail", None) or str(error)
                logger.warning("Auto-import analysis of %s failed: %s", meeting.id, detail)
                return Activity(_now(), transcript, "imported", f"Imported; analysis failed: {detail}", str(meeting.id), meeting.title)
            logger.info("Auto-imported and analyzed %s as meeting %s", transcript, meeting.id)
            return Activity(_now(), transcript, "analyzed", "Imported and analyzed.", str(meeting.id), meeting.title)


class AutoImportWorker:
    """Background thread that calls `run` every few seconds (auto-import, meeting bots)."""

    def __init__(self, importer: AutoImporter | None, interval_seconds: int, run: Callable[[], object], name: str = "auto-import"):
        self.importer, self.interval, self._run, self.name = importer, max(5, interval_seconds), run, name
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"yuqta-{name}", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info("%s worker started (every %ss)", self.name, self.interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self._run()
            except Exception:  # noqa: BLE001 - never let the worker die
                logger.exception("%s poll crashed", self.name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


auto_importer = AutoImporter()
