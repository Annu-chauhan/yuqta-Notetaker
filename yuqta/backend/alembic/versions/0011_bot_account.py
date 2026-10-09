"""meeting_bots.account_email: the registered account whose calendar the meeting is on

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meeting_bots", sa.Column("account_email", sa.String(length=320), nullable=True))
    op.alter_column("minutes_emails", "admin_email", type_=sa.String(length=1000))


def downgrade() -> None:
    op.alter_column("minutes_emails", "admin_email", type_=sa.String(length=320))
    op.drop_column("meeting_bots", "account_email")
