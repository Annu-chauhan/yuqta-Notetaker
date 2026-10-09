"""minutes_emails and meeting_bots.attendee_emails: meeting minutes by email

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meeting_bots", sa.Column("attendee_emails", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "minutes_emails",
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('awaiting_approval', 'sent', 'failed', 'skipped')", name=op.f("ck_minutes_emails_status")),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], name=op.f("fk_minutes_emails_meeting_id_meetings"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("meeting_id", name=op.f("pk_minutes_emails")),
    )


def downgrade() -> None:
    op.drop_table("minutes_emails")
    op.drop_column("meeting_bots", "attendee_emails")
