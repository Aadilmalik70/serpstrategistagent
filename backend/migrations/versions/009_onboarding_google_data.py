"""Add persistent onboarding and Google data connector state.

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_states",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_step", sa.String(length=32), server_default="profile", nullable=False),
        sa.Column("completed_steps", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("data", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="in_progress", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_onboarding_workspace_user"),
    )
    op.create_index("ix_onboarding_states_workspace_id", "onboarding_states", ["workspace_id"])
    op.create_index("ix_onboarding_states_user_id", "onboarding_states", ["user_id"])

    op.create_table(
        "google_data_connections",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("connected_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("google_account_id", sa.String(length=255), nullable=False),
        sa.Column("google_email", sa.String(length=320), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("granted_scopes", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("selected_gsc_property", sa.String(length=2048), nullable=True),
        sa.Column("selected_ga4_property", sa.String(length=255), nullable=True),
        sa.Column("selected_ga4_property_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="connected", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "google_account_id", name="uq_google_data_workspace_account"),
    )
    op.create_index("ix_google_data_connections_workspace_id", "google_data_connections", ["workspace_id"])

    op.create_table(
        "google_oauth_states",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("return_path", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index("ix_google_oauth_states_workspace_id", "google_oauth_states", ["workspace_id"])
    op.create_index("ix_google_oauth_states_user_id", "google_oauth_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_google_oauth_states_user_id", table_name="google_oauth_states")
    op.drop_index("ix_google_oauth_states_workspace_id", table_name="google_oauth_states")
    op.drop_table("google_oauth_states")
    op.drop_index("ix_google_data_connections_workspace_id", table_name="google_data_connections")
    op.drop_table("google_data_connections")
    op.drop_index("ix_onboarding_states_user_id", table_name="onboarding_states")
    op.drop_index("ix_onboarding_states_workspace_id", table_name="onboarding_states")
    op.drop_table("onboarding_states")
