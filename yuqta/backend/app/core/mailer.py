"""Sends email through the configured SMTP server (task reminders, meeting minutes)."""

from email.message import EmailMessage
import logging
import re
import smtplib
import ssl

from app.core.config import Settings


logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class MailError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def mail_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def parse_addresses(value: str | list[str]) -> list[str]:
    """Comma/semicolon separated (or a list) -> unique valid addresses, lower case, in order."""
    raw = value if isinstance(value, list) else re.split(r"[,;\s]+", value or "")
    seen: dict[str, None] = {}
    for address in raw:
        address = address.strip().strip("<>").lower()
        if address and EMAIL_PATTERN.match(address):
            seen.setdefault(address, None)
    return list(seen)


def send_email(settings: Settings, to: list[str], subject: str, text: str, html: str) -> None:
    if not mail_configured(settings):
        raise MailError("Email is not set up. Set SMTP_HOST and SMTP_FROM (see .env.example).", 409)
    if not to:
        raise MailError("No recipients.", 422)
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, settings.smtp_from, ", ".join(to)
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=30, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
            server.starttls(context=ssl.create_default_context())
        with server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as error:
        raise MailError("The email server rejected the login (check SMTP_USER and SMTP_PASSWORD; Gmail needs an app password).") from error
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"Could not send the email: {error.__class__.__name__}: {error}") from error
    logger.info("Email sent to %d recipient(s): %s", len(to), subject)
