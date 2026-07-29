"""Add evidence-backed SERP Content creation workflow.

Revision ID: 025
Revises: 024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _json(default: str):
    del default
    return postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "content_opportunities",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", _uuid(), nullable=False), sa.Column("site_id", _uuid(), nullable=False),
        sa.Column("page_id", _uuid()), sa.Column("opportunity_key", sa.String(160), nullable=False),
        sa.Column("opportunity_type", sa.String(64), nullable=False), sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("title", sa.String(500), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("target_query", sa.String(500)), sa.Column("target_path", sa.String(2048)),
        sa.Column("priority_score", sa.Integer(), server_default="0", nullable=False), sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False), sa.Column("effort_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evidence", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("site_id", "opportunity_key", name="uq_content_opportunity_site_key"),
    )
    op.create_index("ix_content_opportunities_site_status_priority", "content_opportunities", ["site_id", "status", "priority_score"])

    op.create_table(
        "content_briefs",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("workspace_id", _uuid(), nullable=False), sa.Column("site_id", _uuid(), nullable=False), sa.Column("opportunity_id", _uuid()), sa.Column("page_id", _uuid()), sa.Column("status", sa.String(32), server_default="draft", nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("target_query", sa.String(500)), sa.Column("search_intent", sa.String(64), server_default="informational", nullable=False), sa.Column("page_type", sa.String(64), server_default="guide", nullable=False), sa.Column("audience", sa.String(500), server_default="", nullable=False), sa.Column("business_goal", sa.String(500), server_default="", nullable=False),
        sa.Column("outline", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("required_topics", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("required_entities", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("internal_link_targets", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("faq_questions", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("schema_recommendations", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("information_gain", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("evidence", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("scores", _json("'{}'::jsonb"), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["opportunity_id"], ["content_opportunities.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_briefs_site_status_updated", "content_briefs", ["site_id", "status", "updated_at"])

    op.create_table(
        "content_drafts",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("workspace_id", _uuid(), nullable=False), sa.Column("site_id", _uuid(), nullable=False), sa.Column("brief_id", _uuid(), nullable=False), sa.Column("action_id", _uuid()), sa.Column("status", sa.String(32), server_default="draft", nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("slug", sa.String(500), server_default="", nullable=False), sa.Column("meta_title", sa.String(500), server_default="", nullable=False), sa.Column("meta_description", sa.String(1024), server_default="", nullable=False), sa.Column("body_markdown", sa.Text(), server_default="", nullable=False), sa.Column("generation_mode", sa.String(64), server_default="evidence_scaffold", nullable=False), sa.Column("word_count", sa.Integer(), server_default="0", nullable=False), sa.Column("version", sa.Integer(), server_default="1", nullable=False), sa.Column("quality_summary", _json("'{}'::jsonb"), server_default=sa.text("'{}'::jsonb"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["brief_id"], ["content_briefs.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["action_id"], ["operator_actions.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_drafts_site_status_updated", "content_drafts", ["site_id", "status", "updated_at"])

    op.create_table(
        "content_draft_versions",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("draft_id", _uuid(), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("meta_title", sa.String(500), server_default="", nullable=False), sa.Column("meta_description", sa.String(1024), server_default="", nullable=False), sa.Column("body_markdown", sa.Text(), server_default="", nullable=False), sa.Column("generation_mode", sa.String(64), server_default="manual", nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("draft_id", "version", name="uq_content_draft_version"),
    )
    op.create_table(
        "content_quality_checks",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("workspace_id", _uuid(), nullable=False), sa.Column("site_id", _uuid(), nullable=False), sa.Column("draft_id", _uuid(), nullable=False), sa.Column("overall_score", sa.Integer(), server_default="0", nullable=False), sa.Column("passed", sa.Boolean(), server_default=sa.text("false"), nullable=False), sa.Column("checks", _json("'[]'::jsonb"), server_default=sa.text("'[]'::jsonb"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_quality_checks_draft_created", "content_quality_checks", ["draft_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_content_quality_checks_draft_created", table_name="content_quality_checks")
    op.drop_table("content_quality_checks")
    op.drop_table("content_draft_versions")
    op.drop_index("ix_content_drafts_site_status_updated", table_name="content_drafts")
    op.drop_table("content_drafts")
    op.drop_index("ix_content_briefs_site_status_updated", table_name="content_briefs")
    op.drop_table("content_briefs")
    op.drop_index("ix_content_opportunities_site_status_priority", table_name="content_opportunities")
    op.drop_table("content_opportunities")
