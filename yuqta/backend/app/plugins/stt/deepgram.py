"""Deepgram pre-recorded transcription with speaker diarization.

API: POST https://api.deepgram.com/v1/listen (raw audio body, `Authorization: Token <key>`).
Docs: https://developers.deepgram.com/docs/pre-recorded-audio
"""

import logging

import httpx

from app.plugins.stt.base import STTError
from app.schemas.transcript import AudioInput, SegmentIn, TranscriptResult


logger = logging.getLogger(__name__)

LISTEN_URL = "https://api.deepgram.com/v1/listen"


class DeepgramSTTProvider:
    name = "deepgram"

    def __init__(self, api_key: str, model: str = "nova-3", language: str = "en", transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise STTError("STT_PROVIDER=deepgram needs DEEPGRAM_API_KEY.")
        self.model = model
        self.language = language
        # Deepgram allows up to 10 minutes of processing for pre-recorded audio.
        self._http = httpx.Client(
            timeout=httpx.Timeout(600.0, connect=10.0),
            headers={"Authorization": f"Token {api_key}"},
            transport=transport,
        )

    def transcribe(self, audio: AudioInput) -> TranscriptResult:
        params = {
            "model": self.model,
            "language": self.language,
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "diarize_model": "latest",
        }
        if audio.data:
            request = {"content": audio.data, "headers": {"Content-Type": audio.mime_type or "application/octet-stream"}}
        elif audio.source_uri and audio.source_uri.startswith(("https://", "http://")):
            request = {"json": {"url": audio.source_uri}}
        else:
            raise STTError("Deepgram needs audio data or an http(s) audio URL.")

        try:
            response = self._http.post(LISTEN_URL, params=params, **request)
        except httpx.TimeoutException as error:
            raise STTError("Deepgram timed out transcribing the audio.") from error
        except httpx.HTTPError as error:
            raise STTError(f"Could not reach Deepgram: {error.__class__.__name__}") from error

        if response.status_code in (401, 403):
            raise STTError("Deepgram rejected the API key (check DEEPGRAM_API_KEY).")
        if not response.is_success:
            raise STTError(f"Deepgram error {response.status_code}: {_error_message(response)}")

        segments = _segments(response.json())
        logger.info("Deepgram %s transcribed %d utterances", self.model, len(segments))
        return TranscriptResult(provider=self.name, language=self.language, segments=segments)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or "no details"
    return str(body.get("err_msg") or body.get("message") or body.get("err_code") or "no details")[:200]


def _segments(body: dict) -> list[SegmentIn]:
    results = body.get("results") or {}
    utterances = results.get("utterances") or []
    if utterances:
        return [
            SegmentIn(
                speaker=f"Speaker {int(item['speaker']) + 1}" if item.get("speaker") is not None else "Unknown speaker",
                text=item.get("transcript", ""),
                start_seconds=item.get("start"),
                end_seconds=item.get("end"),
            )
            for item in utterances
        ]
    # No utterances (e.g. very short audio): fall back to the full channel transcript.
    channels = results.get("channels") or []
    alternatives = (channels[0].get("alternatives") or []) if channels else []
    text = alternatives[0].get("transcript", "") if alternatives else ""
    return [SegmentIn(speaker="Unknown speaker", text=text)] if text.strip() else []
