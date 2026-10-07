"""meeting_bots: notetaker bots sent into live calls

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_bots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("meeting_url", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider_status", sa.String(length=60), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('joining', 'waiting', 'in_call', 'recording', 'processing', 'transcribed', 'analyzed', 'failed')",
            name=op.f("ck_meeting_bots_status"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"], ["meetings.id"], name=op.f("fk_meeting_bots_meeting_id_meetings"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_bots")),
        sa.UniqueConstraint("provider", "external_id", name="uq_meeting_bots_provider_external_id"),
    )
    op.create_index(op.f("ix_meeting_bots_meeting_id"), "meeting_bots", ["meeting_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_meeting_bots_meeting_id"), table_name="meeting_bots")
    op.drop_table("meeting_bots")
