from pathlib import Path

from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.plugins.stt.base import STTError, STTProvider
from app.plugins.stt.mock import MockSTTProvider


def build_stt_provider(settings: Settings) -> STTProvider:
    if settings.stt_provider == "mock":
        return MockSTTProvider(Path(settings.sample_transcript_path))
    if settings.stt_provider == "deepgram":
        from app.plugins.stt.deepgram import DeepgramSTTProvider

        return DeepgramSTTProvider(settings.deepgram_api_key, model=settings.deepgram_model, language=settings.stt_language)
    raise STTError(f"Unknown STT provider: {settings.stt_provider}")


def get_stt_provider() -> STTProvider:
    """The configured provider, used for uploaded audio. Override in tests to inject a fake."""
    try:
        return build_stt_provider(get_settings())
    except STTError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def get_sample_stt_provider() -> STTProvider:
    """The demo meeting always comes from the fixture transcript, whatever STT_PROVIDER is."""
    return MockSTTProvider(Path(get_settings().sample_transcript_path))
