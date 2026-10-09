from datetime import datetime
from functools import lru_cache
import re
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "Yuqta"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql://yuqta:yuqta@localhost:5433/yuqta"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # Shared secret between the Next.js server and this API. Empty = no API auth (local dev).
    api_auth_token: str = ""
    # Docker mounts ./data at /data; locally the repo's data/ folder is used.
    seed_sql_path: str = str(Path(__file__).resolve().parents[3] / "data" / "seed.sql")
    # Load the demo customers (Acme, Beta, Gamma) into an empty database on startup.
    demo_business_data: bool = True
    sample_transcript_path: str = str(Path(__file__).resolve().parents[3] / "data" / "sample_transcript.json")

    stt_provider: Literal["mock", "deepgram"] = "mock"
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    stt_language: str = "en"
    max_audio_mb: int = 200
    llm_provider: str = "mock"  # mock | openrouter | anthropic
    llm_api_key: str = ""
    llm_model: str = "typesafe/jev-router"  # OpenRouter id; Claude ids only with LLM_PROVIDER=anthropic
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    google_mode: Literal["mock", "live"] = "mock"
    google_client_id: str = ""
    google_client_secret: str = ""
    # Google redirects the browser here; it must be the backend's public URL.
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Where the browser is sent back to after connecting Google.
    frontend_url: str = "http://localhost:3000"
    # Auto-import: Meet "transcript ready" events delivered to this Pub/Sub topic, pulled from this subscription.
    #   projects/<project-id>/topics/<topic>   and   projects/<project-id>/subscriptions/<subscription>
    # Encrypts stored connector tokens so the Google connection survives restarts (empty: memory only).
    # Generate:  python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    token_encryption_key: str = ""
    google_pubsub_topic: str = ""
    google_pubsub_subscription: str = ""
    auto_import_poll_seconds: int = 15

    # Meeting bot: a "Yuqta Notetaker" participant that joins a call, records it and hands back the transcript.
    # mock: simulated bot (no key).  recall: Recall.ai (https://www.recall.ai), needs RECALL_API_KEY.
    meeting_bot_provider: Literal["mock", "recall"] = "mock"
    recall_api_key: str = ""
    # The region your Recall.ai workspace lives in (pay-as-you-go accounts are us-west-2).
    recall_region: Literal["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"] = "us-west-2"
    # Language of the meeting bot's transcript. "auto" detects it and follows switches between languages
    # in one meeting (e.g. Hindi and English, Hinglish). Or a fixed code such as en or hi.
    recall_language: str = "auto"
    # Who transcribes the bot's recording. recallai: Recall.ai's own transcription (no extra setup).
    # deepgram: Deepgram nova-3 through Recall.ai; add your Deepgram API key and project id in the
    # Recall.ai dashboard (same region) first. aws: Amazon Transcribe through Recall.ai; add an AWS access key
    # (IAM user allowed transcribe:StartStreamTranscription*) in the Recall.ai dashboard first.
    # All three follow language switches (e.g. Hindi/English) within one meeting.
    bot_transcription: Literal["recallai", "deepgram", "aws"] = "recallai"
    # AWS Transcribe: languages to detect and switch between (first = preferred), as AWS language codes.
    aws_language_options: str = "en-IN,hi-IN"
    bot_name: str = "Yuqta Notetaker"
    # Posted in the meeting chat (to everyone) as soon as the bot joins, so participants know they are
    # recorded. Empty = no message (not recommended: recording people usually requires their consent).
    bot_consent_message: str = "Hi, I'm Yuqta Notetaker. This meeting is being recorded and transcribed to create notes and action items for the team. If you do not want to be recorded, please tell the host now."
    # Daily task reminder email (off unless SMTP_HOST, SMTP_FROM and REMINDER_TO are set).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    reminder_to: str = ""  # comma-separated addresses
    reminder_hour: int = 9
    # Meeting minutes email after a bot-recorded meeting is analyzed.
    # off | review (held until someone clicks Send on the meeting page) | auto (sent at once, unless a
    # recipient is outside your organisation: then it waits for approval).
    minutes_email: Literal["off", "review", "auto"] = "off"
    minutes_to: str = ""  # always receive the minutes, e.g. the team list (comma-separated)
    internal_domains: str = ""
    # Who gets the recording with the summary when a meeting has no calendar organizer (bots sent by hand).
    meeting_admin_email: str = ""  # e.g. iqlytics.in; addresses elsewhere count as external  # local hour (DISPLAY_TIMEZONE) after which the day's reminder is sent
    # Calendar auto-join: send the bot to every Google Meet on the connected Google Calendar.
    auto_join_calendar: bool = False
    auto_join_hours_ahead: int = 24
    auto_join_poll_seconds: int = 120
    bot_poll_seconds: int = 15
    # IANA time zone for times shown to people (e.g. Asia/Kolkata); the frontend reads the same variable.
    display_timezone: str = "UTC"

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def auto_import_configured(self) -> bool:
        return bool(self.google_pubsub_topic and self.google_pubsub_subscription)

    @field_validator("google_pubsub_topic")
    @classmethod
    def topic_format(cls, value: str) -> str:
        if value and not re.fullmatch(r"projects/[\w.:-]+/topics/[\w.~%+-]+", value):
            raise ValueError("GOOGLE_PUBSUB_TOPIC must look like projects/<project-id>/topics/<topic>")
        return value

    @field_validator("google_pubsub_subscription")
    @classmethod
    def subscription_format(cls, value: str) -> str:
        if value and not re.fullmatch(r"projects/[\w.:-]+/subscriptions/[\w.~%+-]+", value):
            raise ValueError("GOOGLE_PUBSUB_SUBSCRIPTION must look like projects/<project-id>/subscriptions/<name>")
        return value

    @field_validator("bot_consent_message")
    @classmethod
    def consent_message_fits(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) > 500:  # Google Meet's chat limit
            raise ValueError("BOT_CONSENT_MESSAGE must be at most 500 characters (the Google Meet chat limit).")
        return value

    @field_validator("display_timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"DISPLAY_TIMEZONE must be an IANA time zone such as Asia/Kolkata, not {value!r}") from error
        return value

    @field_validator("google_redirect_uri", "frontend_url", mode="before")
    @classmethod
    def blank_means_default(cls, value: str, info) -> str:
        # .env.example ships these keys empty; treat empty as "use the default".
        return value or cls.model_fields[info.field_name].default

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        # Accept the conventional postgresql:// URL and select the psycopg 3 driver.
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def local_time(value: datetime, fmt: str) -> str:
    """Formats an aware datetime in DISPLAY_TIMEZONE, followed by the zone's abbreviation (e.g. "10:29 IST")."""
    local = value.astimezone(ZoneInfo(get_settings().display_timezone))
    return f"{local.strftime(fmt)} {local.tzname()}"
