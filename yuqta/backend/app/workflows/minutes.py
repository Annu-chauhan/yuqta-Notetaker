"""Meeting minutes email: summary, decisions, tasks, risks and open questions, sent after the meeting.

after_analysis() runs when a bot-recorded meeting has been analyzed. MINUTES_EMAIL decides what happens:
- off: nothing;
- review: the email waits on the meeting page until someone clicks Send;
- auto: it is sent at once, unless a recipient is external (not in MINUTES_TO or INTERNAL_DOMAINS),
  in which case it waits for approval too.
A meeting's minutes are sent at most once automatically; re-analysis never re-sends them.
Recipients are the calendar event's attendees (when the bot came from calendar auto-join) plus MINUTES_TO.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, local_time
from app.core.mailer import MailError, mail_configured, parse_addresses, send_email
from app.db.models import ActionItem, Meeting, MeetingBot, MinutesEmail
from app.workflows.analyze_meeting import load_analysis


logger = logging.getLogger(__name__)
FONT = "font-family:Segoe UI,Arial,sans-serif"


class MinutesError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Minutes:
    subject: str
    text: str
    html: str


def suggested_recipients(db: Session, settings: Settings, meeting_id: UUID) -> list[str]:
    bot = db.scalars(select(MeetingBot).where(MeetingBot.meeting_id == meeting_id).order_by(MeetingBot.created_at.desc())).first()
    attendees = parse_addresses(bot.attendee_emails or []) if bot else []
    return parse_addresses(attendees + parse_addresses(settings.minutes_to))


def external_recipients(settings: Settings, recipients: list[str]) -> list[str]:
    """Addresses outside the organisation: not listed in MINUTES_TO and not in INTERNAL_DOMAINS."""
    trusted = set(parse_addresses(settings.minutes_to))
    domains = {d.strip().lower().lstrip("@") for d in settings.internal_domains.split(",") if d.strip()}
    return [a for a in recipients if a not in trusted and a.rsplit("@", 1)[1] not in domains]


def build_minutes(db: Session, settings: Settings, meeting: Meeting) -> Minutes:
    analysis = load_analysis(db, meeting.id)
    if analysis is None:
        raise MinutesError("Analyze the meeting first.", 409)
    info = analysis.meeting
    when = local_time(meeting.occurred_at or meeting.created_at, "%a %d %b %Y, %H:%M")
    tasks = list(db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.id)))
    link = f"{settings.frontend_url.rstrip('/')}/meetings/{meeting.id}"
    participants = ", ".join(row.speaker for row in info.participation) or ", ".join(meeting.participants) or "—"
    summary = info.summary or analysis.summary.headline

    text = [f"Minutes: {meeting.title}", f"{when} · Participants: {participants}", "", "SUMMARY", summary, ""]
    html = [
        "<!doctype html><html><head><meta charset='utf-8'></head><body>",
        f"<div style='{FONT};color:#172420;max-width:680px'>",
        f"<h2 style='margin:0'>Minutes: {escape(meeting.title)}</h2>",
        f"<p style='color:#64716b;margin:4px 0 16px'>{escape(when)} · Participants: {escape(participants)}</p>",
        f"<p style='line-height:1.5'>{escape(summary)}</p>",
    ]

    def section(title: str, lines: list[str], html_items: list[str]) -> None:
        if not lines:
            return
        text.extend([title.upper(), *[f"- {line}" for line in lines], ""])
        html.append(f"<h3 style='margin:20px 0 6px'>{escape(title)}</h3><ul style='margin:0;padding-left:20px;line-height:1.5'>")
        html.extend(f"<li>{item}</li>" for item in html_items)
        html.append("</ul>")

    section("Decisions", [d.text for d in info.decisions], [escape(d.text) for d in info.decisions])
    if tasks:
        def due(task: ActionItem) -> str:
            return f"{task.due_date:%a %d %b}" if task.due_date else (task.due_text or "no date")

        text.extend(["ACTION ITEMS", *[f"- {t.task} — {t.owner or 'Unassigned'}, {due(t)}" for t in tasks], ""])
        html.append(
            "<h3 style='margin:20px 0 6px'>Action items</h3>"
            "<table style='border-collapse:collapse;width:100%'><tr style='text-align:left;color:#64716b'>"
            "<th style='padding:4px 8px 4px 0'>Task</th><th style='padding:4px 8px'>Owner</th><th style='padding:4px 0'>Due</th></tr>"
        )
        for t in tasks:
            owner = escape(t.owner) if t.owner else "<span style='color:#b45309'>Unassigned</span>"
            html.append(
                f"<tr style='border-top:1px solid #e5e9e4'><td style='padding:6px 8px 6px 0'>{escape(t.task)}</td>"
                f"<td style='padding:6px 8px'>{owner}</td><td style='padding:6px 0;white-space:nowrap'>{escape(due(t))}</td></tr>"
            )
        html.append("</table>")
    section("Risks and concerns", [r.text for r in info.risks], [escape(r.text) for r in info.risks])
    section("Open questions", [q.text for q in info.open_questions], [escape(q.text) for q in info.open_questions])
    if not (info.decisions or tasks or info.risks or info.open_questions):
        text.extend(["No decisions, action items, risks or open questions were recorded.", ""])
        html.append("<p style='color:#64716b'>No decisions, action items, risks or open questions were recorded.</p>")

    text.append(f"Transcript and full analysis: {link}")
    html.append(
        f"<p style='margin-top:24px'><a href='{escape(link)}'>Open the transcript and full analysis in Yuqta</a></p>"
        "<p style='color:#64716b;font-size:12px'>Generated by Yuqta from the meeting recording. Reply to correct anything.</p></div></body></html>"
    )
    return Minutes(f"Minutes: {meeting.title} · {when}", "\n".join(text), "".join(html))


def _record(db: Session, meeting_id: UUID, status: str, recipients: list[str], subject: str, detail: str) -> MinutesEmail:
    row = db.get(MinutesEmail, meeting_id) or MinutesEmail(meeting_id=meeting_id)
    row.status, row.recipients, row.subject, row.detail = status, recipients, subject[:300], detail[:2000]
    if status == "sent":
        row.sent_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return row


def after_analysis(db: Session, settings: Settings, meeting_id: UUID) -> MinutesEmail | None:
    """Called when a bot-recorded meeting has been analyzed. Never raises for email problems."""
    if settings.minutes_email == "off" or not mail_configured(settings):
        return None
    existing = db.get(MinutesEmail, meeting_id)
    if existing is not None and existing.status in ("sent", "awaiting_approval"):
        return existing  # already handled; re-analysis never sends again
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        return None
    recipients = suggested_recipients(db, settings, meeting_id)
    if not recipients:
        return _record(db, meeting_id, "skipped", [], "", "No recipients: the meeting had no calendar attendees and MINUTES_TO is empty.")
    minutes = build_minutes(db, settings, meeting)
    external = external_recipients(settings, recipients)
    if settings.minutes_email == "review" or external:
        why = "Waiting for review (MINUTES_EMAIL=review)." if settings.minutes_email == "review" else (
            f"Waiting for approval: {len(external)} recipient(s) outside your organisation ({', '.join(external[:3])}"
            f"{'…' if len(external) > 3 else ''})."
        )
        return _record(db, meeting_id, "awaiting_approval", recipients, minutes.subject, why)
    try:
        send_email(settings, recipients, minutes.subject, minutes.text, minutes.html)
    except MailError as error:
        logger.warning("Minutes email for meeting %s failed: %s", meeting_id, error)
        return _record(db, meeting_id, "failed", recipients, minutes.subject, str(error))
    return _record(db, meeting_id, "sent", recipients, minutes.subject, f"Sent automatically to {len(recipients)} recipient(s).")


def send_minutes(db: Session, settings: Settings, meeting_id: UUID, recipients: list[str]) -> MinutesEmail:
    """Sends (or re-sends) the minutes to the given addresses: the Send button on the meeting page."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise MinutesError("Meeting not found", 404)
    if not mail_configured(settings):  # nothing was attempted, so nothing is recorded as failed
        raise MinutesError("Email is not set up. Set SMTP_HOST and SMTP_FROM (see .env.example).", 409)
    to = parse_addresses(recipients)
    if not to:
        raise MinutesError("Add at least one valid email address.", 422)
    minutes = build_minutes(db, settings, meeting)
    try:
        send_email(settings, to, minutes.subject, minutes.text, minutes.html)
    except MailError as error:
        _record(db, meeting_id, "failed", to, minutes.subject, str(error))
        raise MinutesError(str(error), error.status_code) from error
    return _record(db, meeting_id, "sent", to, minutes.subject, f"Sent to {len(to)} recipient(s).")
