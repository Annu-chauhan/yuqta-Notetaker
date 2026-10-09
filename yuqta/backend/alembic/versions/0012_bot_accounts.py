"""meeting_bots.account_email holds every registered account with the meeting

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("meeting_bots", "account_email", type_=sa.String(length=1000))


def downgrade() -> None:
    op.alter_column("meeting_bots", "account_email", type_=sa.String(length=320))
