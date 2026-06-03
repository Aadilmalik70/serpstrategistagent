"""Add tech detection and fix actions tables

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tech stack and integration columns to sites
    op.add_column("sites", sa.Column("tech_stack", sa.String(50), nullable=True))
    op.add_column("sites", sa.Column("cms", sa.String(50), nullable=True))
    op.add_column("sites", sa.Column("github_repo", sa.String(255), nullable=True))
    op.add_column("sites", sa.Column("github_token", sa.String(255), nullable=True))
    op.add_column("sites", sa.Column("wordpress_url", sa.String(255), nullable=True))
    op.add_column("sites", sa.Column("wordpress_user", sa.String(255), nullable=True))
    op.add_column("sites", sa.Column("wordpress_app_password", sa.String(255), nullable=True))
    op.add_column("sites", sa.Column("site_context", JSONB, nullable=True))

    # Fix actions table — tracks proposed and executed fixes
    op.create_table(
        "fix_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_id", UUID(as_uuid=True), sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),  # github_pr, wordpress_update, recommendation
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),  # pending, approved, executing, completed, rejected, failed
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("fix_content", JSONB, nullable=True),  # The actual fix payload
        sa.Column("target_path", sa.String(500), nullable=True),
        sa.Column("execution_result", JSONB, nullable=True),  # PR URL, WP response, etc.
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fix_actions_site_id", "fix_actions", ["site_id"])
    op.create_index("ix_fix_actions_status", "fix_actions", ["status"])


def downgrade() -> None:
    op.drop_table("fix_actions")
    op.drop_column("sites", "site_context")
    op.drop_column("sites", "wordpress_app_password")
    op.drop_column("sites", "wordpress_user")
    op.drop_column("sites", "wordpress_url")
    op.drop_column("sites", "github_token")
    op.drop_column("sites", "github_repo")
    op.drop_column("sites", "cms")
    op.drop_column("sites", "tech_stack")
