"""Daily task reminder email: overdue, due today and due in the next days, grouped by owner.

Sent once a day after REMINDER_HOUR (DISPLAY_TIMEZONE) to REMINDER_TO through SMTP (for Gmail: smtp.gmail.com,
port 587, and an app password). Nothing is sent when there is nothing due, unless sent by hand as a test.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
import logging
import threading
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.mailer import MailError, mail_configured, parse_addresses, registered_emails, send_email
from app.db.models import ActionItem, Meeting, ReminderLog
from app.workflows.action_items import today


logger = logging.getLogger(__name__)
SOON_DAYS = 3


class ReminderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    overdue: int
    due_today: int
    due_soon: int

    @property
    def empty(self) -> bool:
        return not (self.overdue or self.due_today or self.due_soon)


def build_digest(db: Session, frontend_url: str, on: date | None = None) -> Digest:
    now = on or today()
    rows = db.execute(
        select(ActionItem, Meeting)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(ActionItem.status != "done", ActionItem.due_date.is_not(None), ActionItem.due_date <= now + timedelta(days=SOON_DAYS))
        .order_by(ActionItem.due_date, ActionItem.id)
    ).all()
    groups: dict[str, list[tuple[ActionItem, Meeting]]] = {}
    for item, meeting in rows:
        groups.setdefault(item.owner or "Unassigned", []).append((item, meeting))
    overdue = sum(1 for item, _ in rows if item.due_date < now)
    due_today = sum(1 for item, _ in rows if item.due_date == now)
    due_soon = len(rows) - overdue - due_today

    def when(item: ActionItem) -> str:
        if item.due_date < now:
            days = (now - item.due_date).days
            return f"OVERDUE by {days} day{'s' if days != 1 else ''} (was due {item.due_date:%a %d %b})"
        if item.due_date == now:
            return "due TODAY"
        return f"due {item.due_date:%a %d %b}"

    link = f"{frontend_url.rstrip('/')}/history"
    parts = [f"{overdue} overdue", f"{due_today} due today", f"{due_soon} due in the next {SOON_DAYS} days"]
    subject = f"Yuqta tasks for {now:%a %d %b}: " + ", ".join(p for p in parts if not p.startswith("0 ")) if rows else (
        f"Yuqta tasks for {now:%a %d %b}: nothing due"
    )
    lines = [f"Task reminder for {now:%A %d %B %Y}", ""]
    html = [f"<h2 style='font-family:sans-serif'>Task reminder for {now:%A %d %B %Y}</h2>"]
    if not rows:
        lines.append(f"Nothing is overdue or due in the next {SOON_DAYS} days.")
        html.append(f"<p style='font-family:sans-serif'>Nothing is overdue or due in the next {SOON_DAYS} days.</p>")
    for owner in sorted(groups, key=lambda name: (name == "Unassigned", name.casefold())):
        lines.append(f"{owner}:")
        html.append(f"<h3 style='font-family:sans-serif;margin-bottom:4px'>{escape(owner)}</h3><ul style='font-family:sans-serif'>")
        for item, meeting in groups[owner]:
            lines.append(f"  - {item.task} — {when(item)} — from “{meeting.title}”")
            color = "#b91c1c" if item.due_date < now else ("#b45309" if item.due_date == now else "#374151")
            html.append(
                f"<li>{escape(item.task)} — <strong style='color:{color}'>{escape(when(item))}</strong>"
                f" <span style='color:#6b7280'>· from “{escape(meeting.title)}”</span></li>"
            )
        lines.append("")
        html.append("</ul>")
    lines.append(f"Open your tasks: {link}")
    html.append(f"<p style='font-family:sans-serif'><a href='{escape(link)}'>Open your tasks in Yuqta</a></p>")
    return Digest(subject, "\n".join(lines), "".join(html), overdue, due_today, due_soon)


def _recipients(settings: Settings) -> list[str]:
    # REMINDER_TO, or else the registered (connected) Google account.
    return parse_addresses(settings.reminder_to) or registered_emails(settings)[:1]


def configured(settings: Settings) -> bool:
    return bool(mail_configured(settings) and _recipients(settings))


def send(settings: Settings, digest: Digest) -> list[str]:
    if not configured(settings):
        raise ReminderError("Reminders are not set up. Connect Google on the Import page (allow sending email), "
                            "or set SMTP_HOST, SMTP_FROM and REMINDER_TO (see .env.example).", 409)
    recipients = _recipients(settings)
    try:
        send_email(settings, recipients, digest.subject, digest.text, digest.html)
    except MailError as error:
        raise ReminderError(str(error).replace("send the email", "send the reminder"), error.status_code) from error
    logger.info("Task reminder sent to %d recipient(s): %s", len(recipients), digest.subject)
    return recipients


class ReminderScheduler:
    """Sends the digest once a day after REMINDER_HOUR. Safe to call often (e.g. every 10 minutes)."""

    def __init__(self) -> None:
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def run_once(self, settings: Settings, session_factory, now: datetime | None = None) -> bool:
        if not configured(settings):
            return False
        with self._lock, session_factory() as db:
            local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.display_timezone))
            if local.hour < settings.reminder_hour or db.get(ReminderLog, local.date()) is not None:
                return False
            digest = build_digest(db, settings.frontend_url, on=local.date())
            if digest.empty:
                db.add(ReminderLog(day=local.date(), recipients="", subject="(nothing due, not sent)"))
                db.commit()
                return False
            try:
                recipients = send(settings, digest)
            except ReminderError as error:
                self.last_error = str(error)  # retried on the next run
                logger.warning("Task reminder failed: %s", error)
                return False
            self.last_error = None
            db.add(ReminderLog(day=local.date(), recipients=", ".join(recipients), subject=digest.subject))
            db.commit()
            return True


reminder_scheduler = ReminderScheduler()
