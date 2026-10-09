"""Removing one item (a task, decision, risk or open question) from a meeting's stored analysis.

The item disappears everywhere it was shown: the meeting intelligence, the next step derived from it,
and the meeting's dashboard (its list widget and "At a glance" count). Re-running the analysis brings
back whatever the transcript still supports.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import DashboardSpec, Meeting, MeetingInsight


ItemKind = Literal["action_items", "decisions", "risks", "open_questions"]
_TEXT_FIELD = {"action_items": "task", "decisions": "text", "risks": "text", "open_questions": "text"}
_WIDGET_ID = {"decisions": "decisions", "risks": "risks", "open_questions": "open_questions"}


class EditError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _recommendation_title(kind: ItemKind, text: str) -> str | None:
    """The title meeting_recommendations() gave the next step derived from this item (decisions have none)."""
    return {
        "action_items": text,
        "risks": f"Plan how to handle: {text.rstrip('.')}",
        "open_questions": f"Find an answer: {text}",
    }.get(kind)


def remove_item(db: Session, meeting_id: UUID, kind: ItemKind, index: int, text: str) -> None:
    """Removes item `index` of `kind`; `text` must match, so a stale page never removes the wrong item."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise EditError("Meeting not found", 404)
    header = db.scalars(
        select(MeetingInsight).where(MeetingInsight.meeting_id == meeting_id, MeetingInsight.insight_type == "summary")
    ).first()
    items = ((header.payload or {}).get("meeting") or {}).get(kind) if header else None
    if not items or not 0 <= index < len(items) or items[index].get(_TEXT_FIELD[kind]) != text:
        raise EditError("This item has changed or was already removed. Refresh the page.", 409)

    item = items.pop(index)
    if kind == "action_items":
        from app.workflows.action_items import remove_task

        remove_task(db, meeting_id, text)
    flag_modified(header, "payload")
    segment = (item.get("evidence") or {}).get("segment_index")
    title = _recommendation_title(kind, text)

    removed_keys: set[str] = set()
    if title is not None:
        for row in db.scalars(
            select(MeetingInsight).where(MeetingInsight.meeting_id == meeting_id, MeetingInsight.insight_type == "recommendation")
        ):
            evidence = row.payload.get("evidence") or []
            if row.payload.get("title") == title and evidence and evidence[0].get("segment_index") == segment:
                removed_keys.add(row.payload.get("key"))
                db.delete(row)
                break  # one item produced one next step

    spec_row = db.scalars(select(DashboardSpec).where(DashboardSpec.meeting_id == meeting_id)).first()
    if spec_row is not None:
        widgets = []
        for widget in spec_row.spec.get("widgets", []):
            if widget.get("type") == "points" and widget.get("id") == _WIDGET_ID.get(kind):
                widget["items"] = [
                    point for point in widget["items"]
                    if not (point.get("text") == text and (point.get("evidence") or {}).get("segment_index") == segment)
                ]
                if not widget["items"]:
                    continue  # an empty list is not shown at all
            elif widget.get("type") == "recommendations" and removed_keys:
                widget["items"] = [rec for rec in widget["items"] if rec.get("key") not in removed_keys]
            elif widget.get("type") == "kpis":
                for kpi in widget.get("kpis", []):
                    if kpi.get("key") == kind and isinstance(kpi.get("value"), (int, float)):
                        kpi["value"] = max(0, kpi["value"] - 1)
            widgets.append(widget)
        spec_row.spec = {**spec_row.spec, "widgets": widgets}
        flag_modified(spec_row, "spec")
    db.commit()
