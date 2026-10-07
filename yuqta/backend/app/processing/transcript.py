from collections.abc import Iterable

from app.schemas.transcript import SegmentIn


def normalize_segments(segments: Iterable[SegmentIn]) -> list[SegmentIn]:
    """Collapse whitespace, drop empty turns, default blank speakers, order by start time when known."""
    cleaned: list[SegmentIn] = []
    for segment in segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        speaker = " ".join(segment.speaker.split()) or "Unknown speaker"
        cleaned.append(segment.model_copy(update={"text": text, "speaker": speaker}))

    if all(segment.start_seconds is not None for segment in cleaned):
        cleaned.sort(key=lambda segment: segment.start_seconds)  # stable: ties keep input order
    return cleaned


def speakers(segments: Iterable[SegmentIn]) -> list[str]:
    """Distinct speakers in order of first appearance."""
    return list(dict.fromkeys(segment.speaker for segment in segments))
