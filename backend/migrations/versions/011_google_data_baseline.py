"""Add Google data baseline synchronization metadata.

Revision ID: 011
Revises: 010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "google_data_connections",
        sa.Column("baseline_status", sa.String(length=32), server_default="not_started", nullable=False),
    )
    op.add_column(
        "google_data_connections",
        sa.Column("baseline_summary", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "google_data_connections",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_data_connections", "last_synced_at")
    op.drop_column("google_data_connections", "baseline_summary")
    op.drop_column("google_data_connections", "baseline_status")
