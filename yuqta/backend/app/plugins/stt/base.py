from typing import Protocol

from app.schemas.transcript import AudioInput, TranscriptResult


class STTError(Exception):
    """Raised when a provider cannot produce a transcript."""


class STTProvider(Protocol):
    """Speech-to-text capability. Implementations: MockSTTProvider now, Deepgram later."""

    name: str

    def transcribe(self, audio: AudioInput) -> TranscriptResult: ...
