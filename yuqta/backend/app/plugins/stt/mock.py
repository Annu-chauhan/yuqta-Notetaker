import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.plugins.stt.base import STTError
from app.schemas.transcript import AudioInput, SegmentIn, TranscriptResult


logger = logging.getLogger(__name__)


class MockSTTProvider:
    """Returns the fixture transcript from data/sample_transcript.json for any audio input."""

    name = "mock"

    def __init__(self, fixture_path: Path):
        self.fixture_path = fixture_path

    def load_fixture(self) -> dict:
        try:
            return json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise STTError(f"Mock transcript fixture unreadable: {self.fixture_path}") from error

    def transcribe(self, audio: AudioInput) -> TranscriptResult:
        fixture = self.load_fixture()
        logger.info("Mock STT returning fixture transcript (%s)", self.fixture_path.name)
        try:
            segments = [SegmentIn.model_validate(segment) for segment in fixture.get("segments", [])]
        except ValidationError as error:
            raise STTError("Mock transcript fixture has invalid segments") from error
        return TranscriptResult(provider=self.name, language=fixture.get("language", "en"), segments=segments)
