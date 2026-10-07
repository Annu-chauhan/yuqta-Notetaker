from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings


router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system")
def system_info(settings: Settings = Depends(get_settings)) -> dict:
    """Which providers are active (never the keys), so the UI can describe what will happen."""
    return {
        "stt_provider": settings.stt_provider,
        "stt_model": settings.deepgram_model if settings.stt_provider == "deepgram" else None,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider in ("anthropic", "openrouter") else None,
        "google_mode": settings.google_mode,
        "meeting_bot_provider": settings.meeting_bot_provider,
        "bot_name": settings.bot_name,
        "max_audio_mb": settings.max_audio_mb,
        # Demo features (sample meeting, demo customers) are offered only when this is on.
        "demo_mode": settings.demo_business_data,
    }
