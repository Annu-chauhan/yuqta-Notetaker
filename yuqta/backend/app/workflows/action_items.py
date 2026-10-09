"""Action items as trackable tasks: synced from each analysis, then owned by the people doing them.

Each analysis lists the meeting's action items; sync_action_items() keeps the action_items table in step:
new tasks start "open", untouched tasks the transcript no longer supports are removed, and for tasks that
remain the status and any manual edits (owner, due date) are kept, so re-running an analysis never undoes
your work. A model often rewords a task on a re-run, so tasks are matched by wording, then by the transcript
line they came from, then by similar wording. Tasks you have worked on are never silently deleted.
"""

from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics.due_dates import parse_due
from app.core.config import get_settings
from app.db.models import ActionItem, Meeting, MeetingInsight
from app.schemas.analysis import ActionItem as ExtractedAction


STATUSES = ("open", "in_progress", "done")


def _key(task: str) -> str:
    return " ".join(task.casefold().split()).rstrip(".")


def local_date(value: datetime) -> date:
    """The calendar day of `value` in DISPLAY_TIMEZONE (naive values are treated as UTC)."""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(get_settings().display_timezone)).date()


def today() -> date:
    return local_date(datetime.now(timezone.utc))


def meeting_day(meeting: Meeting) -> date:
    return local_date(meeting.occurred_at or meeting.created_at or datetime.now(timezone.utc))


_SAME_LINE_SIMILARITY = 0.35  # same source line: a loose wording match is enough
_SIMILARITY = 0.75


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _key(a), _key(b)).ratio()


def _match(item: ExtractedAction, rows: list[ActionItem]) -> ActionItem | None:
    """The tracked task this extracted item is (a possibly reworded) version of, among rows not yet matched."""
    key = _key(item.task)
    exact = next((row for row in rows if _key(row.task) == key), None)
    if exact is not None:
        return exact
    scored = [
        (_similarity(item.task, row.task) + (0.5 if row.segment_index == item.evidence.segment_index else 0), row)
        for row in rows
    ]
    for score, row in sorted(scored, key=lambda pair: -pair[0]):
        same_line = row.segment_index == item.evidence.segment_index
        if (same_line and score - 0.5 >= _SAME_LINE_SIMILARITY) or (not same_line and score >= _SIMILARITY):
            return row
    return None


def sync_action_items(db: Session, meeting: Meeting, items: list[ExtractedAction]) -> None:
    """Brings the meeting's tracked tasks in line with its analysis. The caller commits."""
    unmatched = list(db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.id)))
    existing = list(unmatched)
    reference = meeting_day(meeting)
    keep: set[int] = set()
    for item in items:
        row = _match(item, unmatched)
        if row is not None:
            unmatched.remove(row)
        due_date = parse_due(item.due, reference)
        if row is None:
            row = ActionItem(meeting_id=meeting.id, task=item.task, status="open")
            db.add(row)
        row.task = item.task
        row.segment_index = item.evidence.segment_index
        row.speaker = item.evidence.speaker
        row.quote = item.evidence.quote
        if not row.edited:  # manual owner / due date edits win over a re-run analysis
            row.owner, row.due_text, row.due_date = item.owner, item.due, due_date
        db.flush()
        keep.add(row.id)
    # Tasks someone worked on (status changed or edited) stay; only untouched ones disappear with the analysis.
    stale = [row.id for row in existing if row.id not in keep and row.status == "open" and not row.edited]
    if stale:
        db.execute(delete(ActionItem).where(ActionItem.id.in_(stale)))


def backfill(db: Session) -> int:
    """Creates tasks for meetings analyzed before task tracking existed. Returns how many meetings it synced."""
    tracked = select(ActionItem.meeting_id).distinct()
    headers = db.scalars(
        select(MeetingInsight).where(MeetingInsight.insight_type == "summary", MeetingInsight.meeting_id.not_in(tracked))
    ).all()
    synced = 0
    for header in headers:
        items = ((header.payload or {}).get("meeting") or {}).get("action_items") or []
        meeting = db.get(Meeting, header.meeting_id)
        if items and meeting is not None and meeting.status == "analyzed":
            sync_action_items(db, meeting, [ExtractedAction.model_validate(item) for item in items])
            synced += 1
    if synced:
        db.commit()
    return synced


def remove_task(db: Session, meeting_id, task: str) -> None:
    """Called when an action item is removed from a meeting's analysis. The caller commits."""
    for row in db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting_id)):
        if _key(row.task) == _key(task):
            db.delete(row)


class TaskError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


_UNSET = object()


def update_task(db: Session, task_id: int, status: str | None = None, owner=_UNSET, due_date=_UNSET) -> ActionItem:
    row = db.get(ActionItem, task_id)
    if row is None:
        raise TaskError("Action item not found", 404)
    if status is not None:
        if status not in STATUSES:
            raise TaskError(f"Status must be one of {', '.join(STATUSES)}.", 422)
        if status == "done" and row.status != "done":
            row.completed_at = datetime.now(timezone.utc)
        elif status != "done":
            row.completed_at = None
        row.status = status
    if owner is not _UNSET:
        row.owner = (" ".join(owner.split())[:200] or None) if owner else None
        row.edited = True
    if due_date is not _UNSET:
        row.due_date = due_date
        row.due_text = None  # the spoken wording ("by friday") no longer describes a date set by hand
        row.edited = True
    db.commit()
    return row
