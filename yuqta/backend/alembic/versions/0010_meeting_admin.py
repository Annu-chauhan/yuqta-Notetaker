"""meeting admin: who gets the recording link with the summary

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meeting_bots", sa.Column("admin_email", sa.String(length=320), nullable=True))
    op.add_column("minutes_emails", sa.Column("admin_email", sa.String(length=320), nullable=True))
    op.add_column("minutes_emails", sa.Column("admin_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("minutes_emails", sa.Column("admin_detail", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("minutes_emails", "admin_detail")
    op.drop_column("minutes_emails", "admin_sent_at")
    op.drop_column("minutes_emails", "admin_email")
    op.drop_column("meeting_bots", "admin_email")
