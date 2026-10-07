"""meetings.external_ref for idempotent imports

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("external_ref", sa.String(length=300), nullable=True))
    op.create_unique_constraint(op.f("uq_meetings_external_ref"), "meetings", ["external_ref"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_meetings_external_ref"), "meetings", type_="unique")
    op.drop_column("meetings", "external_ref")
