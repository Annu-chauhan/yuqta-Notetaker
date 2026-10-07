"""dashboards are deleted with their meeting

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_dashboard_specs_meeting_id_meetings"


def upgrade() -> None:
    op.execute("DELETE FROM dashboard_specs WHERE meeting_id IS NULL")  # orphans from deleted meetings
    op.alter_column("dashboard_specs", "meeting_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(op.f(_FK), "dashboard_specs", type_="foreignkey")
    op.create_foreign_key(op.f(_FK), "dashboard_specs", "meetings", ["meeting_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint(op.f(_FK), "dashboard_specs", type_="foreignkey")
    op.create_foreign_key(op.f(_FK), "dashboard_specs", "meetings", ["meeting_id"], ["id"], ondelete="SET NULL")
    op.alter_column("dashboard_specs", "meeting_id", existing_type=sa.Uuid(), nullable=True)
