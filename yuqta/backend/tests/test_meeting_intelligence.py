"""Meeting-first analysis: the meeting's own intelligence, with business data only when relevant."""

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.db import seed
from app.plugins.llm import MockLLMProvider
from app.plugins.llm.extraction import ExtractedAction, ExtractedMeeting, ExtractedPoint, ExtractedTopic, Extraction, validated_meeting
from app.schemas.transcript import SegmentIn


SEGMENTS = [
    SegmentIn(speaker="Gaurav Kumar", text="Let's discuss the new pricing plan for the product."),
    SegmentIn(speaker="Parul Chauhan", text="We agreed to launch the beta in November."),
    SegmentIn(speaker="Gaurav Kumar", text="I will prepare the pricing deck by Friday."),
    SegmentIn(speaker="Parul Chauhan", text="My concern is the delay in the payment integration."),
    SegmentIn(speaker="Gaurav Kumar", text="Who owns the marketing launch?"),
]


def test_model_output_is_validated() -> None:
    extracted = ExtractedMeeting(
        summary="  Pricing   and launch.  ",
        meeting_type="product",
        topics=[ExtractedTopic(title="Pricing", summary="New plan.", segment_index=0),
                ExtractedTopic(title="Invented", summary="x", segment_index=99)],
        decisions=[ExtractedPoint(text="Launch beta in November", segment_index=1)],
        action_items=[ExtractedAction(task="Prepare the pricing deck", owner="gaurav kumar", due="By Friday", segment_index=2),
                      ExtractedAction(task="Ghost task", owner=None, due=None, segment_index=-1)],
        risks=[ExtractedPoint(text="Payment integration delay", segment_index=3)],
        open_questions=[ExtractedPoint(text="", segment_index=4)],
    )
    meeting = validated_meeting(extracted, SEGMENTS)
    assert meeting.summary == "Pricing and launch."
    assert [t.title for t in meeting.topics] == ["Pricing"]  # line 99 does not exist
    [action] = meeting.action_items
    assert (action.owner, action.due) == ("Gaurav Kumar", "by friday")  # owner mapped onto the speaker's spelling
    assert action.evidence.quote == "I will prepare the pricing deck by Friday."  # quote from the transcript itself
    assert meeting.open_questions == []  # empty text dropped
    assert validated_meeting(None, SEGMENTS).summary == ""
    assert Extraction.model_validate({"signals": []}).meeting is None  # lax providers may omit it


def test_mock_finds_decisions_tasks_risks_and_questions() -> None:
    meeting = MockLLMProvider().extract_signals(SEGMENTS, []).meeting
    assert [d.evidence.segment_index for d in meeting.decisions] == [1]
    assert [(a.evidence.segment_index, a.owner, a.due) for a in meeting.action_items] == [
        (0, None, None), (2, "Gaurav Kumar", "by friday")
    ]
    assert [r.evidence.segment_index for r in meeting.risks] == [3]
    assert [q.text for q in meeting.open_questions] == ["Who owns the marketing launch?"]


def test_real_meeting_without_business_talk(seeded_api: TestClient) -> None:
    body = {"title": "Product sync", "segments": [s.model_dump() for s in SEGMENTS]}
    meeting_id = seeded_api.post("/api/meetings", json=body).json()["id"]
    result = seeded_api.post(f"/api/meetings/{meeting_id}/analyze").json()
    assert result["business_context"] is False
    assert result["meeting"]["participation"][0]["speaker"] == "Gaurav Kumar"
    recs = [(r["priority"], r["title"], r["owner"]) for r in result["recommendations"]]
    assert ("medium", "I will prepare the pricing deck by Friday", "Gaurav Kumar") in recs
    assert ("medium", "Plan how to handle: My concern is the delay in the payment integration", None) in recs
    assert ("low", "Find an answer: Who owns the marketing launch?", None) in recs

    spec = seeded_api.get(f"/api/meetings/{meeting_id}/dashboard").json()
    widgets = {w.get("id", w["type"]): w for w in spec["widgets"]}
    assert list(widgets) == ["summary", "kpis", "participation", "decisions", "risks", "open_questions", "recommendations"]
    glance = {k["key"]: k["value"] for k in widgets["kpis"]["kpis"]}
    assert glance == {"participants": 2, "action_items": 2, "decisions": 1, "risks": 1, "open_questions": 1}
    assert widgets["recommendations"]["title"] == "Next steps"
    assert "Acme" not in str(spec)

    stored = seeded_api.get(f"/api/meetings/{meeting_id}/analysis").json()
    assert stored == result  # meeting intelligence survives the round trip through storage


def test_startup_seed_respects_demo_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "get_settings", lambda: Settings(_env_file=None, demo_business_data=False))
    monkeypatch.setattr(seed, "load_seed", lambda *_: pytest.fail("demo data must not load"))
    assert seed.run(if_empty=True) is False
    assert Settings.model_fields["demo_business_data"].default is True  # new installs still get the demo


def test_long_lines_are_quoted_by_the_relevant_sentence() -> None:
    monologue = SegmentIn(
        speaker="Parul",
        text="Hello everyone, let's get started with the agenda for today. The beta version of the app is almost ready "
        "for the team. The payment integration is getting delayed by the gateway team. I will prepare the marketing "
        "budget by next Monday. Okay, thank you all, see you next week. We can meet again on Thursday afternoon "
        "to review where everything stands.",
    )
    extracted = ExtractedMeeting(
        summary="s", meeting_type="product", topics=[], decisions=[],
        action_items=[ExtractedAction(task="Prepare the marketing budget", owner=None, due="next monday", segment_index=0)],
        risks=[ExtractedPoint(text="Payment integration delayed", segment_index=0)], open_questions=[],
    )
    meeting = validated_meeting(extracted, [monologue])
    assert meeting.action_items[0].evidence.quote == "I will prepare the marketing budget by next Monday."
    assert meeting.risks[0].evidence.quote == "The payment integration is getting delayed by the gateway team."
    assert meeting.risks[0].evidence.quote in monologue.text  # always verbatim from the transcript
