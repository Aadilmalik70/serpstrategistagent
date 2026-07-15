"""Add durable governed GitHub execution records.

Revision ID: 022
Revises: 021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("base_commit_sha", sa.String(length=64), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.Text(), nullable=True),
        sa.Column("pull_request_state", sa.String(length=32), nullable=True),
        sa.Column("pull_request_draft", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("changed_files", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rollback", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["operator_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["repository_connection_id"],
            ["github_repository_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_github_executions_action"),
        sa.UniqueConstraint(
            "repository_connection_id",
            "branch_name",
            name="uq_github_executions_connection_branch",
        ),
    )
    op.create_index(
        "ix_github_executions_workspace_status",
        "github_executions",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_github_executions_site_created",
        "github_executions",
        ["site_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_github_executions_site_created", table_name="github_executions")
    op.drop_index("ix_github_executions_workspace_status", table_name="github_executions")
    op.drop_table("github_executions")
