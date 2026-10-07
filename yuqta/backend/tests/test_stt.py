import json
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.plugins.stt import MockSTTProvider, STTError, build_stt_provider
from app.processing.transcript import normalize_segments, speakers
from app.schemas.transcript import AudioInput, SegmentIn


def test_factory_returns_mock_by_default() -> None:
    provider = build_stt_provider(Settings(_env_file=None))
    assert isinstance(provider, MockSTTProvider)
    assert provider.name == "mock"


def test_deepgram_requires_api_key() -> None:
    with pytest.raises(STTError, match="DEEPGRAM_API_KEY"):
        build_stt_provider(Settings(_env_file=None, stt_provider="deepgram"))


def test_mock_returns_sample_transcript() -> None:
    result = MockSTTProvider(Path(get_settings().sample_transcript_path)).transcribe(AudioInput())
    assert result.provider == "mock"
    assert [(s.speaker, s.text) for s in result.segments] == [
        ("Sales Manager", "Enterprise revenue is down this month."),
        ("Finance Manager", "Acme reduced their order significantly."),
        ("Product Manager", "Beta also hasn't renewed yet."),
        ("Sales Manager", "We should contact both customers this week."),
    ]


def test_mock_reports_missing_fixture(tmp_path: Path) -> None:
    with pytest.raises(STTError, match="unreadable"):
        MockSTTProvider(tmp_path / "missing.json").transcribe(AudioInput())


def test_mock_reports_invalid_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "bad.json"
    fixture.write_text(json.dumps({"segments": [{"speaker": "A"}]}), encoding="utf-8")
    with pytest.raises(STTError, match="invalid segments"):
        MockSTTProvider(fixture).transcribe(AudioInput())


def test_segment_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        SegmentIn(text="hi", start_seconds=5, end_seconds=2)


def test_normalize_cleans_drops_and_orders() -> None:
    cleaned = normalize_segments(
        [
            SegmentIn(speaker="  Finance   Manager ", text=" second  point ", start_seconds=4),
            SegmentIn(speaker="Sales Manager", text="   ", start_seconds=2),
            SegmentIn(speaker="   ", text="first point", start_seconds=1),
        ]
    )
    assert [(s.speaker, s.text) for s in cleaned] == [
        ("Unknown speaker", "first point"),
        ("Finance Manager", "second point"),
    ]


def test_normalize_keeps_order_without_timestamps() -> None:
    cleaned = normalize_segments([SegmentIn(speaker="B", text="one"), SegmentIn(speaker="A", text="two")])
    assert [s.text for s in cleaned] == ["one", "two"]
    assert speakers(cleaned) == ["B", "A"]
