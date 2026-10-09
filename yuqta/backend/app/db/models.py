"""ORM models for the POC.

Business data (customers, orders, revenue, renewals) is reference data loaded from
data/seed.sql. Meeting data (meetings, transcript_segments, meeting_insights,
dashboard_specs) is written by the workflow in later phases.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


JSONType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(14, 2)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (CheckConstraint("status IN ('Healthy', 'At Risk', 'Churned')", name="status"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. C001
    name: Mapped[str] = mapped_column(String(200), unique=True)
    industry: Mapped[str] = mapped_column(String(100))
    account_owner: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))

    renewals: Mapped[list["Renewal"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("units >= 0", name="units"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True)
    units: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Money)


class Revenue(Base):
    """Recognised revenue per customer per month. customer_id NULL = long-tail 'Other' accounts."""

    __tablename__ = "revenue"
    __table_args__ = (
        # NULLS NOT DISTINCT: only one 'Other' (NULL customer) row per period.
        UniqueConstraint(
            "period_start", "customer_id", name="uq_revenue_period_customer", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)  # first day of the month
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)


class Renewal(Base):
    __tablename__ = "renewals"
    __table_args__ = (
        CheckConstraint("status IN ('upcoming', 'renewed', 'overdue', 'churned')", name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    contract_value: Mapped[Decimal] = mapped_column(Money)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    renewed_on: Mapped[date | None] = mapped_column(Date)

    customer: Mapped[Customer] = relationship(back_populates="renewals")


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'transcribed', 'analyzed', 'failed')", name="status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(300))
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual | mock_stt | google_meet
    # Where the meeting came from outside Yuqta (e.g. a Meet transcript name); unique so imports are idempotent.
    external_ref: Mapped[str | None] = mapped_column(String(300), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="TranscriptSegment.segment_index"
    )
    insights: Mapped[list["MeetingInsight"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("meeting_id", "segment_index", name="uq_segments_meeting_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    segment_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(200))
    start_seconds: Mapped[float | None]
    end_seconds: Mapped[float | None]
    text: Mapped[str] = mapped_column(Text)

    meeting: Mapped[Meeting] = relationship(back_populates="segments")


class MeetingInsight(Base):
    """One analysis result for a meeting: the summary, a signal, KPI, root cause or recommendation."""

    __tablename__ = "meeting_insights"
    __table_args__ = (
        CheckConstraint(
            "insight_type IN ('summary', 'signal', 'kpi', 'root_cause', 'recommendation')", name="type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    insight_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped[Meeting] = relationship(back_populates="insights")


class MeetingBot(Base):
    """A notetaker bot sent into a live call. When the call ends its transcript becomes a Meeting."""

    __tablename__ = "meeting_bots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'joining', 'waiting', 'in_call', 'recording', 'processing', 'transcribed', 'analyzed', 'failed', 'cancelled')",
            name="status",
        ),
        UniqueConstraint("provider", "external_id", name="uq_meeting_bots_provider_external_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(20))  # mock | recall
    external_id: Mapped[str] = mapped_column(String(100))  # the provider's bot id
    meeting_url: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="joining")
    provider_status: Mapped[str | None] = mapped_column(String(60))  # raw provider status code, for debugging
    # Set for bots scheduled ahead of time: when the bot joins, and the calendar event that caused it.
    join_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_event_id: Mapped[str | None] = mapped_column(String(300), index=True)
    # Email addresses of the calendar event's attendees (who receive the minutes).
    attendee_emails: Mapped[list[str] | None] = mapped_column(JSONType)
    detail: Mapped[str] = mapped_column(Text, default="")
    # The meeting created from the bot's transcript; kept (set NULL) if that meeting is deleted.
    meeting_id: Mapped[UUID | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActionItem(Base):
    """A task agreed in a meeting, tracked until done. Kept in step with the analysis (workflows/action_items.py)."""

    __tablename__ = "action_items"
    __table_args__ = (CheckConstraint("status IN ('open', 'in_progress', 'done')", name="status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(200))
    due_text: Mapped[str | None] = mapped_column(String(100))  # as said, e.g. "by friday"
    due_date: Mapped[date | None] = mapped_column(Date, index=True)  # parsed from due_text, or set by hand
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    edited: Mapped[bool] = mapped_column(default=False)  # owner/due changed by hand: a re-run analysis keeps them
    segment_index: Mapped[int | None]
    speaker: Mapped[str | None] = mapped_column(String(200))
    quote: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MinutesEmail(Base):
    """The minutes email of one meeting: held for approval, sent, or why it was not sent."""

    __tablename__ = "minutes_emails"
    __table_args__ = (
        CheckConstraint("status IN ('awaiting_approval', 'sent', 'failed', 'skipped')", name="status"),
    )

    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    recipients: Mapped[list[str]] = mapped_column(JSONType, default=list)
    subject: Mapped[str] = mapped_column(String(300), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReminderLog(Base):
    """One row per day a task reminder was handled, so it is sent at most once a day."""

    __tablename__ = "reminder_log"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    recipients: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorCredential(Base):
    """Encrypted credentials of a connector (app/db/credentials.py), e.g. the Google OAuth tokens."""

    __tablename__ = "connector_credentials"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. google:live
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DashboardSpec(Base):
    __tablename__ = "dashboard_specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A dashboard is derived from one meeting's analysis, so it goes when the meeting goes.
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
