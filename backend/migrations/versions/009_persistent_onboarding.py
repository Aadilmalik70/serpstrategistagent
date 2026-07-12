"""Add persistent onboarding state.

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
        sa.Column("onboarding_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_step", sa.String(length=64), server_default="profile", nullable=False),
        sa.Column("completed_steps", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("answers", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="in_progress", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_onboarding_workspace_user"),
    )
    op.create_index("ix_onboarding_states_workspace_id", "onboarding_states", ["workspace_id"])
    op.create_index("ix_onboarding_states_user_id", "onboarding_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_states_user_id", table_name="onboarding_states")
    op.drop_index("ix_onboarding_states_workspace_id", table_name="onboarding_states")
    op.drop_table("onboarding_states")
