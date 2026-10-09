"""connector_credentials: encrypted connector tokens that survive restarts

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_credentials",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_connector_credentials")),
    )


def downgrade() -> None:
    op.drop_table("connector_credentials")
