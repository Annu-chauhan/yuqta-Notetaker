from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.plugins.stt import STTError, get_sample_stt_provider, get_stt_provider
from app.schemas.transcript import AudioInput, TranscriptResult


def test_create_sample_meeting_runs_mock_stt(api: TestClient) -> None:
    response = api.post("/api/meetings/sample")
    assert response.status_code == 201
    meeting = response.json()
    assert meeting["title"] == "Enterprise Revenue Review"
    assert meeting["participants"] == ["Sales Manager", "Finance Manager", "Product Manager"]
    assert meeting["source"] == "mock_stt"
    assert meeting["status"] == "transcribed"
    assert meeting["segment_count"] == 4
    assert [s["segment_index"] for s in meeting["segments"]] == [0, 1, 2, 3]
    assert meeting["segments"][1] == {
        "segment_index": 1,
        "speaker": "Finance Manager",
        "text": "Acme reduced their order significantly.",
        "start_seconds": 3.6,
        "end_seconds": 6.9,
    }


def test_get_and_list_meetings(api: TestClient) -> None:
    created = api.post("/api/meetings/sample").json()
    detail = api.get(f"/api/meetings/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["segments"] == created["segments"]

    listing = api.get("/api/meetings").json()
    assert [(m["id"], m["segment_count"]) for m in listing] == [(created["id"], 4)]
    assert "segments" not in listing[0]


def test_unknown_meeting_is_404(api: TestClient) -> None:
    assert api.get(f"/api/meetings/{uuid4()}").status_code == 404
    assert api.get("/api/meetings/not-a-uuid").status_code == 422


def test_create_meeting_from_segments(api: TestClient) -> None:
    response = api.post(
        "/api/meetings",
        json={
            "title": "  Pipeline sync ",
            "segments": [
                {"speaker": "Ari", "text": "Conversion is up 4%."},
                {"speaker": "Sam", "text": "   "},
                {"speaker": "Sam", "text": "We will  follow up."},
            ],
        },
    )
    assert response.status_code == 201
    meeting = response.json()
    assert meeting["title"] == "Pipeline sync"
    assert meeting["source"] == "manual"
    assert meeting["participants"] == ["Ari", "Sam"]  # derived from speakers when not supplied
    assert [s["text"] for s in meeting["segments"]] == ["Conversion is up 4%.", "We will follow up."]


def test_create_meeting_rejects_empty_transcript(api: TestClient) -> None:
    response = api.post("/api/meetings", json={"title": "Empty", "segments": [{"text": "  "}]})
    assert response.status_code == 422
    assert response.json()["detail"] == "Transcript has no spoken text."
    assert api.get("/api/meetings").json() == []


def test_create_meeting_validates_input(api: TestClient) -> None:
    assert api.post("/api/meetings", json={"title": "", "segments": [{"text": "x"}]}).status_code == 422
    assert api.post("/api/meetings", json={"title": "No segments", "segments": []}).status_code == 422


def test_stt_failure_marks_meeting_failed(api: TestClient) -> None:
    class FailingSTT:
        name = "mock"

        def transcribe(self, audio: AudioInput) -> TranscriptResult:
            raise STTError("audio unreadable")

    app.dependency_overrides[get_sample_stt_provider] = lambda: FailingSTT()
    response = api.post("/api/meetings/sample")
    assert response.status_code == 502
    assert response.json()["detail"] == "Transcription failed: audio unreadable"
    meetings = api.get("/api/meetings").json()
    assert [(m["status"], m["segment_count"]) for m in meetings] == [("failed", 0)]


def test_deepgram_without_key_is_503_for_uploads(api: TestClient, monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "stt_provider", "deepgram")
    monkeypatch.setattr(config.get_settings(), "deepgram_api_key", "")
    response = api.post("/api/meetings/audio", data={"title": "x"}, files={"file": ("a.wav", b"RIFF", "audio/wav")})
    assert response.status_code == 503
    assert "DEEPGRAM_API_KEY" in response.json()["detail"]
    # The demo meeting still works: it always uses the fixture transcript.
    assert api.post("/api/meetings/sample").status_code == 201
