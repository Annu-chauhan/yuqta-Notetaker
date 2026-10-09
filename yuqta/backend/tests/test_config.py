import pytest

from app.core.config import Settings


def test_postgres_url_uses_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://yuqta:yuqta@postgres:5432/yuqta")
    assert settings.database_url == "postgresql+psycopg://yuqta:yuqta@postgres:5432/yuqta"


def test_explicit_driver_is_kept() -> None:
    url = "postgresql+psycopg://u:p@db:5432/x"
    assert Settings(database_url=url).database_url == url


def test_defaults_need_no_external_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("STT_PROVIDER", "LLM_PROVIDER", "GOOGLE_MODE", "DEEPGRAM_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.stt_provider == "mock"
    assert settings.llm_provider == "mock"
    assert settings.google_mode == "mock"
    assert settings.deepgram_api_key == ""


def test_invalid_google_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, google_mode="sometimes")


def test_display_timezone_is_validated() -> None:
    assert Settings(_env_file=None, display_timezone="Asia/Kolkata").display_timezone == "Asia/Kolkata"
    with pytest.raises(ValueError, match="IANA time zone"):
        Settings(_env_file=None, display_timezone="India")


def test_local_time_uses_display_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.core import config

    when = datetime(2026, 10, 8, 4, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(config, "get_settings", lambda: Settings(_env_file=None, display_timezone="Asia/Kolkata"))
    assert config.local_time(when, "%d %b, %H:%M") == "08 Oct, 09:59 IST"
    monkeypatch.setattr(config, "get_settings", lambda: Settings(_env_file=None))
    assert config.local_time(when, "%H:%M") == "04:29 UTC"
