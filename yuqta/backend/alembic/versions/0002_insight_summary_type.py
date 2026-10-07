"""allow 'summary' meeting insights

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_meeting_insights_type"


def upgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "meeting_insights", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "meeting_insights",
        "insight_type IN ('summary', 'signal', 'kpi', 'root_cause', 'recommendation')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM meeting_insights WHERE insight_type = 'summary'")
    op.drop_constraint(op.f(_CONSTRAINT), "meeting_insights", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "meeting_insights",
        "insight_type IN ('signal', 'kpi', 'root_cause', 'recommendation')",
    )
