from functools import lru_cache

from app.connectors.meeting_bot.base import BotError, BotState, MeetingBotClient, normalize_meeting_url
from app.core.config import get_settings


@lru_cache
def _client() -> MeetingBotClient:
    settings = get_settings()
    if settings.meeting_bot_provider == "recall":
        from app.connectors.meeting_bot.recall import RecallMeetingBotClient

        return RecallMeetingBotClient(
            settings.recall_api_key, settings.recall_region, settings.recall_language,
            transcription=settings.bot_transcription, aws_languages=settings.aws_language_options,
        )
    from app.connectors.meeting_bot.mock import MockMeetingBotClient

    return MockMeetingBotClient(settings.sample_transcript_path)


def get_meeting_bot_client() -> MeetingBotClient:
    """FastAPI dependency (one client per process). Override in tests."""
    return _client()


__all__ = ["BotError", "BotState", "MeetingBotClient", "get_meeting_bot_client", "normalize_meeting_url"]
