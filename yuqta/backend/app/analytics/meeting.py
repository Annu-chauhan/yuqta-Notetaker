"""Meeting-first intelligence: what the meeting itself produced, with or without business data."""

from collections.abc import Sequence

from app.schemas.analysis import CorrelatedSignal, MeetingIntelligence, Participation, Recommendation, Signal
from app.schemas.transcript import SegmentIn


_SOON = ("today", "tomorrow", "tonight", "this week", "asap", "immediately", "eod", "end of day")


def discusses_business(signals: Sequence[Signal]) -> bool:
    """True when the meeting talked about known customers or company revenue/sales.

    Only then is the business data (KPIs, root causes, "not discussed" accounts) relevant to this meeting.
    """
    return any(
        signal.customers or (signal.kind == "metric_change" and signal.metric in ("revenue", "sales"))
        for signal in signals
    )


def participation(segments: Sequence[SegmentIn]) -> list[Participation]:
    """Share of the conversation per speaker, by words spoken (works with or without timestamps)."""
    turns: dict[str, int] = {}
    words: dict[str, int] = {}
    for segment in segments:
        turns[segment.speaker] = turns.get(segment.speaker, 0) + 1
        words[segment.speaker] = words.get(segment.speaker, 0) + len(segment.text.split())
    total = sum(words.values()) or 1
    rows = [
        Participation(speaker=speaker, turns=turns[speaker], words=words[speaker], share_pct=round(words[speaker] / total * 100, 1))
        for speaker in turns
    ]
    return sorted(rows, key=lambda row: -row.words)


def meeting_headline(meeting: MeetingIntelligence) -> str:
    if meeting.summary:
        return meeting.summary
    names = [row.speaker for row in meeting.participation]
    return f"Meeting with {', '.join(names)}." if names else "Meeting analyzed."


def meeting_recommendations(meeting: MeetingIntelligence, signals: Sequence[CorrelatedSignal]) -> list[Recommendation]:
    """Next steps from the meeting: agreed tasks, then risks and open questions that need an owner.

    Lines already turned into a customer follow-up by the business rules are skipped, so nothing is listed twice.
    """
    covered = {signal.evidence.segment_index for signal in signals if signal.kind == "action_item"}
    recommendations: list[Recommendation] = []
    for item in meeting.action_items:
        if item.evidence.segment_index in covered:
            continue
        soon = bool(item.due) and any(word in item.due for word in _SOON)
        recommendations.append(
            Recommendation(
                key=f"task:{item.evidence.segment_index}:{len(recommendations)}",
                title=item.task,
                priority="high" if soon else "medium",
                owner=item.owner,
                due=item.due,
                rationale=["Agreed in the meeting"] + ([] if item.owner else ["No owner was named: assign one"]),
                evidence=[item.evidence],
            )
        )
    for risk in meeting.risks:
        recommendations.append(
            Recommendation(
                key=f"risk:{risk.evidence.segment_index}:{len(recommendations)}",
                title=f"Plan how to handle: {risk.text.rstrip('.')}",
                priority="medium",
                rationale=["Risk raised in the meeting without an agreed action"],
                evidence=[risk.evidence],
            )
        )
    for question in meeting.open_questions:
        recommendations.append(
            Recommendation(
                key=f"question:{question.evidence.segment_index}:{len(recommendations)}",
                title=f"Find an answer: {question.text}",
                priority="low",
                rationale=["Question left open in the meeting"],
                evidence=[question.evidence],
            )
        )
    return recommendations
