"""Add encrypted Google data connections.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_data_connections",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_tokens", sa.Text(), nullable=True),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("oauth_state_hash", sa.String(length=64), nullable=True),
        sa.Column("oauth_state_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="not_connected", nullable=False),
        sa.Column("google_email", sa.String(length=320), nullable=True),
        sa.Column("scopes", JSONB(), server_default="[]", nullable=False),
        sa.Column("gsc_property", sa.String(length=2048), nullable=True),
        sa.Column("ga4_property_id", sa.String(length=128), nullable=True),
        sa.Column("ga4_property_name", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_google_data_workspace_user"),
        sa.UniqueConstraint("oauth_state_hash"),
    )
    op.create_index("ix_google_data_connections_workspace_id", "google_data_connections", ["workspace_id"])
    op.create_index("ix_google_data_connections_user_id", "google_data_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_google_data_connections_user_id", table_name="google_data_connections")
    op.drop_index("ix_google_data_connections_workspace_id", table_name="google_data_connections")
    op.drop_table("google_data_connections")
