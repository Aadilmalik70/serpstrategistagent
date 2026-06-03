"""Add agent_runs and issues tables

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("trigger", sa.String(20), server_default="manual", nullable=False),
        sa.Column("pages_analyzed", sa.Integer, server_default="0", nullable=False),
        sa.Column("issues_found", sa.Integer, server_default="0", nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "issues",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", UUID(as_uuid=True), sa.ForeignKey("pages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_run_id", UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=True),
        sa.Column("affected_url", sa.String(2048), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_issues_site_id", "issues", ["site_id"])
    op.create_index("ix_issues_severity", "issues", ["severity"])
    op.create_index("ix_agent_runs_site_id", "agent_runs", ["site_id"])


def downgrade() -> None:
    op.drop_table("issues")
    op.drop_table("agent_runs")
