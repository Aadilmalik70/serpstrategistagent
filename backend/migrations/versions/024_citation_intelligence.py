"""Add provider-safe AI citation intelligence state.

Revision ID: 024
Revises: 023
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "citation_prompt_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand_terms", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("competitor_terms", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("prompts", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("providers", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("schedule_interval_hours", sa.Integer()),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_citation_prompt_set_site_name"),
    )
    op.create_index("ix_citation_prompt_sets_site_status", "citation_prompt_sets", ["site_id", "status", "updated_at"])

    op.create_table(
        "citation_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("citation_prompt_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("providers", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("prompt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("visibility_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mention_rate", sa.Float(), server_default="0", nullable=False),
        sa.Column("citation_rate", sa.Float(), server_default="0", nullable=False),
        sa.Column("competitor_metrics", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_citation_scans_site_status_created", "citation_scans", ["site_id", "status", "created_at"])
    op.create_index("ix_citation_scans_workspace_created", "citation_scans", ["workspace_id", "created_at"])

    op.create_table(
        "citation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("citation_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer_excerpt", sa.Text(), server_default="", nullable=False),
        sa.Column("brand_mentioned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cited_urls", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("competitor_mentions", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "provider", "prompt_hash", name="uq_citation_result_scan_provider_prompt"),
    )
    op.create_index("ix_citation_results_scan_provider", "citation_results", ["scan_id", "provider"])

    op.create_table(
        "citation_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("citation_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_actions.id", ondelete="SET NULL")),
        sa.Column("gap_key", sa.String(128), nullable=False),
        sa.Column("gap_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("competitor", sa.String(255)),
        sa.Column("priority_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "gap_key", name="uq_citation_gap_site_key"),
    )
    op.create_index("ix_citation_gaps_site_status_priority", "citation_gaps", ["site_id", "status", "priority_score"])


def downgrade() -> None:
    op.drop_index("ix_citation_gaps_site_status_priority", table_name="citation_gaps")
    op.drop_table("citation_gaps")
    op.drop_index("ix_citation_results_scan_provider", table_name="citation_results")
    op.drop_table("citation_results")
    op.drop_index("ix_citation_scans_workspace_created", table_name="citation_scans")
    op.drop_index("ix_citation_scans_site_status_created", table_name="citation_scans")
    op.drop_table("citation_scans")
    op.drop_index("ix_citation_prompt_sets_site_status", table_name="citation_prompt_sets")
    op.drop_table("citation_prompt_sets")
