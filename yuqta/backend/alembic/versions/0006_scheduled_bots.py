"""meeting_bots: scheduled and cancelled bots (calendar auto-join)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "status IN ('joining', 'waiting', 'in_call', 'recording', 'processing', 'transcribed', 'analyzed', 'failed')"
_NEW = "status IN ('scheduled', 'joining', 'waiting', 'in_call', 'recording', 'processing', 'transcribed', 'analyzed', 'failed', 'cancelled')"


def upgrade() -> None:
    op.add_column("meeting_bots", sa.Column("join_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("meeting_bots", sa.Column("calendar_event_id", sa.String(length=300), nullable=True))
    op.create_index(op.f("ix_meeting_bots_calendar_event_id"), "meeting_bots", ["calendar_event_id"], unique=False)
    op.drop_constraint(op.f("ck_meeting_bots_status"), "meeting_bots", type_="check")
    op.create_check_constraint(op.f("ck_meeting_bots_status"), "meeting_bots", _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM meeting_bots WHERE status = 'scheduled'")
    op.execute("UPDATE meeting_bots SET status = 'failed' WHERE status = 'cancelled'")
    op.drop_constraint(op.f("ck_meeting_bots_status"), "meeting_bots", type_="check")
    op.create_check_constraint(op.f("ck_meeting_bots_status"), "meeting_bots", _OLD)
    op.drop_index(op.f("ix_meeting_bots_calendar_event_id"), table_name="meeting_bots")
    op.drop_column("meeting_bots", "calendar_event_id")
    op.drop_column("meeting_bots", "join_at")
