from pydantic import BaseModel, Field, model_validator


class SegmentIn(BaseModel):
    """One speaker turn, as produced by an STT provider or supplied by a connector."""

    speaker: str = Field(default="Unknown speaker", max_length=200)
    text: str = Field(max_length=20_000)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def end_after_start(self) -> "SegmentIn":
        if self.start_seconds is not None and self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not be before start_seconds")
        return self


class AudioInput(BaseModel):
    """What gets transcribed. Real providers will use the URI or bytes; the mock ignores both."""

    source_uri: str | None = None
    data: bytes | None = None
    mime_type: str | None = None


class TranscriptResult(BaseModel):
    provider: str
    language: str = "en"
    segments: list[SegmentIn]
