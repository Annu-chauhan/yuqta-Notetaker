"""action_items and reminder_log: tasks from meetings, tracked until done, with daily reminders

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=True),
        sa.Column("due_text", sa.String(length=100), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("segment_index", sa.Integer(), nullable=True),
        sa.Column("speaker", sa.String(length=200), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'done')", name=op.f("ck_action_items_status")),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], name=op.f("fk_action_items_meeting_id_meetings"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_items")),
    )
    op.create_index(op.f("ix_action_items_meeting_id"), "action_items", ["meeting_id"], unique=False)
    op.create_index(op.f("ix_action_items_due_date"), "action_items", ["due_date"], unique=False)
    op.create_index(op.f("ix_action_items_status"), "action_items", ["status"], unique=False)
    op.create_table(
        "reminder_log",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("recipients", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_reminder_log")),
    )


def downgrade() -> None:
    op.drop_table("reminder_log")
    op.drop_index(op.f("ix_action_items_status"), table_name="action_items")
    op.drop_index(op.f("ix_action_items_due_date"), table_name="action_items")
    op.drop_index(op.f("ix_action_items_meeting_id"), table_name="action_items")
    op.drop_table("action_items")
