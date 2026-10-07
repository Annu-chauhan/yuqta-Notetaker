"""Deepgram provider and audio upload, against a mock HTTP transport (no key, no network)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.plugins.stt import STTError, build_stt_provider, get_stt_provider
from app.plugins.stt.deepgram import DeepgramSTTProvider
from app.schemas.transcript import AudioInput


# Shape from https://developers.deepgram.com/docs/pre-recorded-audio (utterances + diarization).
DEEPGRAM_RESPONSE = {
    "metadata": {"request_id": "dg-123"},
    "results": {
        "channels": [{"alternatives": [{"transcript": "Revenue is down. Acme cut orders.", "confidence": 0.98}]}],
        "utterances": [
            {"start": 0.1, "end": 2.4, "transcript": "Enterprise revenue is down this month.", "speaker": 0, "confidence": 0.97},
            {"start": 2.9, "end": 5.2, "transcript": "Acme reduced their order significantly.", "speaker": 1, "confidence": 0.95},
            {"start": 5.6, "end": 7.0, "transcript": "We should contact them this week.", "speaker": 0, "confidence": 0.96},
        ],
    },
}


def _provider(handler) -> DeepgramSTTProvider:
    return DeepgramSTTProvider("dg-key", transport=httpx.MockTransport(handler))


def test_factory_builds_deepgram_with_key() -> None:
    provider = build_stt_provider(Settings(_env_file=None, stt_provider="deepgram", deepgram_api_key="k", deepgram_model="nova-3"))
    assert isinstance(provider, DeepgramSTTProvider) and provider.model == "nova-3"


def test_uploaded_bytes_are_sent_with_diarization_and_mapped_to_speakers() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=request.url, headers=request.headers, body=request.content)
        return httpx.Response(200, json=DEEPGRAM_RESPONSE)

    result = _provider(handler).transcribe(AudioInput(data=b"RIFF....WAVE", mime_type="audio/wav"))

    assert str(seen["url"]).startswith("https://api.deepgram.com/v1/listen?")
    assert dict(seen["url"].params) == {
        "model": "nova-3", "language": "en", "smart_format": "true", "punctuate": "true",
        "utterances": "true", "diarize_model": "latest",
    }
    assert seen["headers"]["authorization"] == "Token dg-key"
    assert seen["headers"]["content-type"] == "audio/wav"
    assert seen["body"] == b"RIFF....WAVE"

    assert result.provider == "deepgram"
    assert [(s.speaker, s.text, s.start_seconds) for s in result.segments] == [
        ("Speaker 1", "Enterprise revenue is down this month.", 0.1),
        ("Speaker 2", "Acme reduced their order significantly.", 2.9),
        ("Speaker 1", "We should contact them this week.", 5.6),
    ]


def test_remote_url_is_sent_as_json() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json=DEEPGRAM_RESPONSE)

    _provider(handler).transcribe(AudioInput(source_uri="https://example.com/call.mp3"))
    assert seen["body"] == b'{"url":"https://example.com/call.mp3"}'


def test_falls_back_to_channel_transcript_without_utterances() -> None:
    body = {"results": {"channels": [{"alternatives": [{"transcript": "Short clip."}]}]}}
    result = _provider(lambda r: httpx.Response(200, json=body)).transcribe(AudioInput(data=b"x", mime_type="audio/wav"))
    assert [(s.speaker, s.text) for s in result.segments] == [("Unknown speaker", "Short clip.")]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"err_code": "INVALID_AUTH"}), "rejected the API key"),
        (httpx.Response(400, json={"err_msg": "Bad Request: failed to process audio: corrupt or unsupported data"}), "corrupt or unsupported"),
        (httpx.Response(504, text="Gateway Timeout"), "Deepgram error 504"),
    ],
)
def test_error_responses(response: httpx.Response, message: str) -> None:
    with pytest.raises(STTError, match=message):
        _provider(lambda r: response).transcribe(AudioInput(data=b"x", mime_type="audio/wav"))


def test_timeout_and_missing_audio() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(STTError, match="timed out"):
        _provider(timeout).transcribe(AudioInput(data=b"x", mime_type="audio/wav"))
    with pytest.raises(STTError, match="needs audio"):
        _provider(lambda r: httpx.Response(200)).transcribe(AudioInput(source_uri="sample://demo"))


# --- POST /api/meetings/audio ---------------------------------------------------------------


@pytest.fixture
def deepgram_api(api: TestClient):
    provider = _provider(lambda r: httpx.Response(200, json=DEEPGRAM_RESPONSE))
    app.dependency_overrides[get_stt_provider] = lambda: provider
    yield api


def test_upload_creates_transcribed_meeting(deepgram_api: TestClient) -> None:
    response = deepgram_api.post(
        "/api/meetings/audio",
        data={"title": " Weekly review ", "participants": "Ari, Sam ,"},
        files={"file": ("call.wav", b"RIFF....WAVE", "audio/wav")},
    )
    assert response.status_code == 201, response.text
    meeting = response.json()
    assert (meeting["title"], meeting["source"], meeting["status"]) == ("Weekly review", "deepgram_stt", "transcribed")
    assert meeting["participants"] == ["Ari", "Sam"]
    assert [s["speaker"] for s in meeting["segments"]] == ["Speaker 1", "Speaker 2", "Speaker 1"]


def test_upload_rejects_non_audio_and_empty_and_large(deepgram_api: TestClient, monkeypatch) -> None:
    from app.core import config

    files = lambda content, mime: {"file": ("f", content, mime)}  # noqa: E731
    assert deepgram_api.post("/api/meetings/audio", data={"title": "x"}, files=files(b"%PDF", "application/pdf")).status_code == 415
    assert deepgram_api.post("/api/meetings/audio", data={"title": "x"}, files=files(b"", "audio/wav")).status_code == 422
    monkeypatch.setattr(config.get_settings(), "max_audio_mb", 1)
    big = deepgram_api.post("/api/meetings/audio", data={"title": "x"}, files=files(b"0" * (1024 * 1024 + 1), "audio/wav"))
    assert (big.status_code, big.json()["detail"]) == (413, "Audio file is larger than 1 MB.")
    assert deepgram_api.post("/api/meetings/audio", files=files(b"x", "audio/wav")).status_code == 422  # title required


def test_upload_transcription_failure_keeps_failed_meeting(api: TestClient) -> None:
    provider = _provider(lambda r: httpx.Response(400, json={"err_msg": "corrupt audio"}))
    app.dependency_overrides[get_stt_provider] = lambda: provider
    response = api.post("/api/meetings/audio", data={"title": "Bad"}, files={"file": ("a.wav", b"x", "audio/wav")})
    assert response.status_code == 502
    assert "corrupt audio" in response.json()["detail"]
    assert [(m["title"], m["status"]) for m in api.get("/api/meetings").json()] == [("Bad", "failed")]
