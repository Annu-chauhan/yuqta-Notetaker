"""Meeting history: what all analyzed meetings produced, side by side.

Reads the stored analysis header of each meeting (one `summary` insight row), so it costs one query
and never re-runs the LLM. Meetings analyzed before meeting-first analysis existed have no meeting
intelligence; they are listed with zero counts.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Meeting, MeetingInsight
from app.schemas.analysis import MeetingIntelligence


class HistoryMeeting(BaseModel):
    id: str
    title: str
    date: datetime
    source: str
    status: str
    headline: str | None
    meeting_type: str | None
    participants: list[str]
    action_items: int = 0
    decisions: int = 0
    risks: int = 0
    open_questions: int = 0


class HistoryItem(BaseModel):
    kind: Literal["action_items", "decisions", "risks", "open_questions"]
    index: int  # position in the meeting's list; with `text`, identifies the item for removal
    text: str
    owner: str | None = None
    due: str | None = None
    meeting_id: str
    meeting_title: str
    date: datetime
    speaker: str
    quote: str


class OwnerLoad(BaseModel):
    owner: str
    action_items: int


class HistoryTotals(BaseModel):
    meetings: int
    analyzed: int
    action_items: int
    unassigned_action_items: int
    decisions: int
    risks: int
    open_questions: int


class History(BaseModel):
    totals: HistoryTotals
    meetings: list[HistoryMeeting]
    action_items: list[HistoryItem]
    decisions: list[HistoryItem]
    risks: list[HistoryItem]
    open_questions: list[HistoryItem]
    owners: list[OwnerLoad]


UNASSIGNED = "Unassigned"


def build_history(db: Session, limit: int = 100) -> History:
    meetings = list(db.scalars(select(Meeting).order_by(Meeting.created_at.desc()).limit(limit)))
    headers = {
        row.meeting_id: row.payload
        for row in db.scalars(
            select(MeetingInsight).where(
                MeetingInsight.insight_type == "summary", MeetingInsight.meeting_id.in_([m.id for m in meetings])
            )
        )
    }

    rows: list[HistoryMeeting] = []
    actions: list[HistoryItem] = []
    decisions: list[HistoryItem] = []
    risks: list[HistoryItem] = []
    questions: list[HistoryItem] = []
    for meeting in meetings:
        date = meeting.occurred_at or meeting.created_at
        header = headers.get(meeting.id) if meeting.status == "analyzed" else None
        intel = MeetingIntelligence.model_validate(header.get("meeting") or {}) if header else MeetingIntelligence()

        def item(kind: str, index: int, text: str, evidence, **extra) -> HistoryItem:
            return HistoryItem(
                kind=kind, index=index, text=text, meeting_id=str(meeting.id), meeting_title=meeting.title, date=date,
                speaker=evidence.speaker, quote=evidence.quote, **extra,
            )

        actions += [item("action_items", i, a.task, a.evidence, owner=a.owner, due=a.due) for i, a in enumerate(intel.action_items)]
        decisions += [item("decisions", i, p.text, p.evidence) for i, p in enumerate(intel.decisions)]
        risks += [item("risks", i, p.text, p.evidence) for i, p in enumerate(intel.risks)]
        questions += [item("open_questions", i, p.text, p.evidence) for i, p in enumerate(intel.open_questions)]
        rows.append(
            HistoryMeeting(
                id=str(meeting.id),
                title=meeting.title,
                date=date,
                source=meeting.source,
                status=meeting.status,
                headline=((header.get("summary") or {}).get("headline") if header else None),
                meeting_type=intel.meeting_type if header and header.get("meeting") else None,
                participants=list(meeting.participants or []),
                action_items=len(intel.action_items),
                decisions=len(intel.decisions),
                risks=len(intel.risks),
                open_questions=len(intel.open_questions),
            )
        )

    load: dict[str, int] = {}
    for action in actions:
        owner = action.owner or UNASSIGNED
        load[owner] = load.get(owner, 0) + 1
    owners = sorted((OwnerLoad(owner=name, action_items=count) for name, count in load.items()),
                    key=lambda row: (row.owner == UNASSIGNED, -row.action_items, row.owner.casefold()))

    return History(
        totals=HistoryTotals(
            meetings=len(rows),
            analyzed=sum(1 for row in rows if row.status == "analyzed"),
            action_items=len(actions),
            unassigned_action_items=load.get(UNASSIGNED, 0),
            decisions=len(decisions),
            risks=len(risks),
            open_questions=len(questions),
        ),
        meetings=rows,
        action_items=actions,
        decisions=decisions,
        risks=risks,
        open_questions=questions,
        owners=owners,
    )
