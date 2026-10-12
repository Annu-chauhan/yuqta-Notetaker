from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionItem, Meeting, MeetingInsight
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.workflows.action_items import STATUSES, TaskError, backfill, today, update_task


router = APIRouter(prefix="/api/action-items", tags=["action items"])

View = Literal["open", "overdue", "due_soon", "done", "all"]


class TaskOut(BaseModel):
    id: int
    meeting_id: str
    meeting_title: str
    meeting_date: datetime
    task: str
    owner: str | None
    due_text: str | None
    due_date: date | None
    status: str
    overdue: bool
    due_today: bool
    edited: bool
    speaker: str | None
    quote: str | None
    completed_at: datetime | None
    index: int | None  # position in the meeting's analysis; with `task`, used to remove it from there


class TaskCounts(BaseModel):
    open: int
    in_progress: int
    overdue: int
    due_today: int
    done: int
    unassigned: int


class TaskList(BaseModel):
    today: date
    counts: TaskCounts
    owners: list[str]
    tasks: list[TaskOut]


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "done"] | None = None
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    # Only fields present in the request are changed; send "owner": null or "due_date": null to clear them.


def _rows(db: Session) -> list[tuple[ActionItem, Meeting]]:
    return list(db.execute(select(ActionItem, Meeting).join(Meeting, Meeting.id == ActionItem.meeting_id)))


def _positions(db: Session, meeting_ids: set) -> dict:
    """(meeting_id, task) -> index in the stored analysis, for removing an item from there."""
    positions = {}
    for header in db.scalars(
        select(MeetingInsight).where(MeetingInsight.insight_type == "summary", MeetingInsight.meeting_id.in_(meeting_ids))
    ):
        for index, item in enumerate(((header.payload or {}).get("meeting") or {}).get("action_items") or []):
            positions.setdefault((header.meeting_id, item.get("task")), index)
    return positions


def build_task_list(db: Session, view: View = "open", owner: str | None = None) -> TaskList:
    backfill(db)
    now = today()
    rows = _rows(db)
    positions = _positions(db, {meeting.id for _, meeting in rows})

    def is_open(item: ActionItem) -> bool:
        return item.status != "done"

    def overdue(item: ActionItem) -> bool:
        return is_open(item) and item.due_date is not None and item.due_date < now

    counts = TaskCounts(
        open=sum(1 for item, _ in rows if item.status == "open"),
        in_progress=sum(1 for item, _ in rows if item.status == "in_progress"),
        overdue=sum(1 for item, _ in rows if overdue(item)),
        due_today=sum(1 for item, _ in rows if is_open(item) and item.due_date == now),
        done=sum(1 for item, _ in rows if item.status == "done"),
        unassigned=sum(1 for item, _ in rows if is_open(item) and not item.owner),
    )
    owners = sorted({item.owner for item, _ in rows if item.owner}, key=str.casefold)

    selected = []
    for item, meeting in rows:
        if owner is not None and (item.owner or "") != owner:
            continue
        if view == "open" and not is_open(item):
            continue
        if view == "overdue" and not overdue(item):
            continue
        if view == "due_soon" and not (is_open(item) and item.due_date is not None and item.due_date <= now + timedelta(days=7)):
            continue
        if view == "done" and is_open(item):
            continue
        selected.append((item, meeting))

    far = date.max
    if view == "done":
        selected.sort(key=lambda pair: pair[0].completed_at or pair[0].updated_at, reverse=True)
    else:  # most urgent first: overdue, then by due date, undated last; newest meeting first within a day
        selected.sort(key=lambda pair: (pair[0].due_date or far, -(pair[1].created_at.timestamp())))

    tasks = [
        TaskOut(
            id=item.id, meeting_id=str(meeting.id), meeting_title=meeting.title,
            meeting_date=meeting.occurred_at or meeting.created_at, task=item.task, owner=item.owner,
            due_text=item.due_text, due_date=item.due_date, status=item.status, overdue=overdue(item),
            due_today=is_open(item) and item.due_date == now, edited=item.edited, speaker=item.speaker,
            quote=item.quote, completed_at=item.completed_at, index=positions.get((meeting.id, item.task)),
        )
        for item, meeting in selected
    ]
    return TaskList(today=now, counts=counts, owners=owners, tasks=tasks)


@router.get("", response_model=TaskList)
def list_tasks(
    view: View = "open",
    owner: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> TaskList:
    """Tracked action items across all meetings. view: open (default), overdue, due_soon (next 7 days), done, all."""
    return build_task_list(db, view, owner)


@router.patch("/{task_id}", response_model=TaskList)
def change_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)) -> TaskList:
    """Changes status, owner or due date. Owner and due date edits survive a re-run analysis."""
    fields = body.model_fields_set
    try:
        update_task(
            db, task_id,
            status=body.status,
            **({"owner": body.owner} if "owner" in fields else {}),
            **({"due_date": body.due_date} if "due_date" in fields else {}),
        )
    except TaskError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return build_task_list(db, "all")


# --- Daily reminder email ------------------------------------------------------------------


@router.get("/reminders")
def reminder_status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """Whether reminders are set up, when the last one went out, and what today's would contain."""
    from app.db.models import ReminderLog
    from app.workflows.reminders import build_digest, configured, reminder_scheduler, _recipients as reminder_recipients

    last = db.scalars(select(ReminderLog).where(ReminderLog.recipients != "").order_by(ReminderLog.day.desc())).first()
    digest = build_digest(db, settings.frontend_url)
    return {
        "configured": configured(settings),
        "recipients": reminder_recipients(settings),  # REMINDER_TO, else the registered Google account
        "hour": settings.reminder_hour,
        "timezone": settings.display_timezone,
        "last_sent": {"day": last.day, "subject": last.subject} if last else None,
        "last_error": reminder_scheduler.last_error,
        "preview": {"subject": digest.subject, "overdue": digest.overdue, "due_today": digest.due_today, "due_soon": digest.due_soon},
    }


@router.post("/reminders/send")
def send_reminder_now(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """Sends today's reminder now (also when nothing is due), e.g. to test the email setup."""
    from app.workflows.reminders import ReminderError, build_digest, send

    digest = build_digest(db, settings.frontend_url)
    try:
        recipients = send(settings, digest)
    except ReminderError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"sent_to": recipients, "subject": digest.subject}


__all__ = ["router", "STATUSES"]
