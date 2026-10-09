"""Recall.ai meeting bots (Google Meet, Zoom, Teams).

API: https://<region>.recall.ai/api/v1/bot/ with `Authorization: Token <key>`.
Docs: https://docs.recall.ai/docs/quickstart and https://docs.recall.ai/docs/bot-status-change-events

The bot is transcribed by Recall.ai (`recallai_streaming`, accuracy mode) or, with BOT_TRANSCRIPTION=deepgram,
by Deepgram nova-3 through Recall.ai (`deepgram_streaming`); either way the finished transcript is a
JSON file behind a pre-signed URL in recordings[].media_shortcuts.transcript.data.download_url.
"""

from datetime import datetime, timezone
import logging

import httpx

from app.connectors.meeting_bot.base import BotError, BotState


logger = logging.getLogger(__name__)


class RecallMeetingBotClient:
    name = "recall"

    def __init__(
        self,
        api_key: str,
        region: str,
        language: str = "auto",
        transport: httpx.BaseTransport | None = None,
        transcription: str = "recallai",
        aws_languages: str = "en-IN,hi-IN",
        consent_message: str = "",
    ):
        if not api_key:
            raise BotError("MEETING_BOT_PROVIDER=recall needs RECALL_API_KEY.", status_code=503)
        self.language = language
        self.transcription = transcription
        self.consent_message = consent_message
        self.aws_languages = [code.strip() for code in aws_languages.split(",") if code.strip()] or ["en-IN", "hi-IN"]
        timeout = httpx.Timeout(30.0, connect=10.0)
        self._api = httpx.Client(
            base_url=f"https://{region}.recall.ai/api/v1",
            timeout=timeout,
            headers={"Authorization": f"Token {api_key}"},
            transport=transport,
        )
        # Pre-signed storage URLs reject an extra Authorization header, so downloads use a plain client.
        self._download = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), transport=transport)

    def create_bot(self, meeting_url: str, bot_name: str, join_at: datetime | None = None) -> str:
        body = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {"transcript": {"provider": self._transcript_provider()}},
            "metadata": {"source": "yuqta"},
        }
        if self.consent_message:
            # Tells everyone in the call that it is recorded, the moment the bot is let in.
            body["chat"] = {"on_bot_join": {"send_to": "everyone", "message": self.consent_message}}
        if join_at is not None:
            # More than 10 minutes ahead makes this a scheduled bot, which Recall.ai guarantees joins on time.
            body["join_at"] = join_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            data = self._request("POST", "/bot/", json=body)
        except BotError as error:
            if self.transcription in _SETUP_HINTS and error.status_code == 400:
                raise BotError(
                    f"{error} {_SETUP_HINTS[self.transcription]}, or set BOT_TRANSCRIPTION=recallai.",
                    status_code=400,
                    permanent=True,
                ) from error
            raise
        bot_id = data.get("id")
        if not isinstance(bot_id, str) or not bot_id:
            raise BotError("Recall.ai did not return a bot id.")
        logger.info("Recall.ai bot %s sent to %s", bot_id, meeting_url)
        return bot_id

    def _transcript_provider(self) -> dict:
        if self.transcription == "aws":
            # Amazon Transcribe identifies each language spoken and follows switches between them.
            return {
                "aws_transcribe_streaming": {
                    "identify_multiple_languages": True,
                    "language_options": ",".join(self.aws_languages),
                    "preferred_language": self.aws_languages[0],
                }
            }
        if self.transcription == "deepgram":
            # nova-3 with language "multi" detects the language and follows switches (e.g. Hindi/English).
            language = "multi" if self.language in ("auto", "multi") else self.language
            return {"deepgram_streaming": {"model": "nova-3", "language": language}}
        return {"recallai_streaming": {"mode": "prioritize_accuracy", "language_code": self.language}}

    def get_bot(self, bot_id: str) -> BotState:
        return bot_state(self._request("GET", f"/bot/{bot_id}/"))

    def get_recording_url(self, bot_id: str) -> str | None:
        # Recall.ai keeps the video and signs a new download link (valid ~6 hours) on every request.
        for recording in self._request("GET", f"/bot/{bot_id}/").get("recordings") or []:
            video = ((recording.get("media_shortcuts") or {}).get("video_mixed")) or {}
            url = (video.get("data") or {}).get("download_url")
            if url and ((video.get("status") or {}).get("code") in (None, "done")):
                return url
        return None

    def delete_scheduled_bot(self, bot_id: str) -> None:
        self._request("DELETE", f"/bot/{bot_id}/")

    def leave_call(self, bot_id: str) -> None:
        self._request("POST", f"/bot/{bot_id}/leave_call/")

    def download_transcript(self, url: str) -> list[dict]:
        try:
            response = self._download.get(url)
        except httpx.HTTPError as error:
            raise BotError(f"Could not download the transcript: {error.__class__.__name__}") from error
        if not response.is_success:
            raise BotError(f"Transcript download failed ({response.status_code}).")
        try:
            data = response.json()
        except ValueError as error:
            raise BotError("The transcript file is not valid JSON.") from error
        if not isinstance(data, list):
            raise BotError("Unexpected transcript format.")
        return [entry for entry in data if isinstance(entry, dict)]

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._api.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            raise BotError("Recall.ai timed out.", status_code=504) from error
        except httpx.HTTPError as error:
            raise BotError(f"Could not reach Recall.ai: {error.__class__.__name__}") from error
        if response.status_code in (401, 403):
            raise BotError("Recall.ai rejected the API key (check RECALL_API_KEY and RECALL_REGION).", status_code=503)
        if response.status_code == 404:
            raise BotError("Recall.ai has no such bot.", status_code=404, permanent=True)
        if response.status_code == 429:
            raise BotError("Recall.ai rate limit reached; try again in a minute.", status_code=429)
        if response.status_code == 400:
            raise BotError(f"Recall.ai refused the request: {_error_message(response)}", status_code=400, permanent=True)
        if not response.is_success:
            raise BotError(f"Recall.ai error {response.status_code}: {_error_message(response)}")
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as error:
            raise BotError("Recall.ai returned an invalid response.") from error
        return data if isinstance(data, dict) else {}


_SETUP_HINTS = {
    "deepgram": "To use Deepgram, add your Deepgram API key and project id in the Recall.ai dashboard",
    "aws": "To use AWS Transcribe, add your AWS access key in the Recall.ai dashboard (Transcription → AWS Transcribe)",
}


def bot_state(data: dict) -> BotState:
    """Reads the latest status and the transcript (if any) from a Recall.ai bot object."""
    changes = [c for c in data.get("status_changes") or [] if isinstance(c, dict)]
    latest = changes[-1] if changes else (data.get("status") if isinstance(data.get("status"), dict) else {})
    recordings = [r for r in data.get("recordings") or [] if isinstance(r, dict)]

    transcript_status, transcript_url = "none", None
    for recording in recordings:
        transcript = ((recording.get("media_shortcuts") or {}).get("transcript")) or {}
        if not transcript:
            continue
        code = str(((transcript.get("status") or {}).get("code")) or "")
        url = (transcript.get("data") or {}).get("download_url")
        if code == "done" and url:
            transcript_status, transcript_url = "done", url
            break
        transcript_status = "failed" if code == "failed" else "processing"

    return BotState(
        code=str(latest.get("code") or "unknown"),
        sub_code=latest.get("sub_code") or None,
        message=latest.get("message") or None,
        recorded=bool(recordings) or any(c.get("code") == "in_call_recording" for c in changes),
        transcript_status=transcript_status,
        transcript_url=transcript_url,
    )


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or "no details"
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message") or body
        if isinstance(detail, dict):  # field errors: {"meeting_url": ["..."]}
            detail = "; ".join(f"{key}: {' '.join(map(str, value)) if isinstance(value, list) else value}" for key, value in detail.items())
        return str(detail)[:300]
    return str(body)[:300]
