"""Add rendered crawl search performance and action measurement state.

Revision ID: 019
Revises: 018
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_job_queue_active_gsc_sync_per_site",
        "job_queue",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'gsc_search_sync' AND status IN ('queued', 'running', 'retry_wait')"
        ),
    )
    op.create_table(
        "search_sync_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("job_queue.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default="running", nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("result", JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_search_sync_attempt_job_number"),
    )
    op.create_index("ix_search_sync_attempts_job_id", "search_sync_attempts", ["job_id"])

    op.create_table(
        "search_analytics_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("query", sa.Text(), server_default="", nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("page_url", sa.String(2048), server_default="", nullable=False),
        sa.Column("page_url_hash", sa.String(64), nullable=False),
        sa.Column("page_url_key_hash", sa.String(64), nullable=False),
        sa.Column("clicks", sa.Float(), server_default="0", nullable=False),
        sa.Column("impressions", sa.Float(), server_default="0", nullable=False),
        sa.Column("ctr", sa.Float(), server_default="0", nullable=False),
        sa.Column("position", sa.Float(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("site_id", "metric_date", "query_hash", "page_url_hash", name="uq_search_metric_site_date_query_page"),
    )
    op.create_index("ix_search_metrics_site_date", "search_analytics_metrics", ["site_id", "metric_date"])
    op.create_index(
        "ix_search_metrics_site_date_page_key",
        "search_analytics_metrics",
        ["site_id", "metric_date", "page_url_key_hash"],
    )
    op.create_index("ix_search_metrics_workspace_date", "search_analytics_metrics", ["workspace_id", "metric_date"])

    op.create_table(
        "search_opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_key", sa.String(64), nullable=False),
        sa.Column("opportunity_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("query", sa.Text()),
        sa.Column("page_url", sa.String(2048)),
        sa.Column("priority_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metrics", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("site_id", "opportunity_key", name="uq_search_opportunity_site_key"),
    )
    op.create_index("ix_search_opportunities_site_status", "search_opportunities", ["site_id", "status", "priority_score"])

    op.create_table(
        "action_measurements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action_id", UUID(as_uuid=True), sa.ForeignKey("operator_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="waiting", nullable=False),
        sa.Column("outcome", sa.String(32), server_default="insufficient_data", nullable=False),
        sa.Column("target_query", sa.Text()),
        sa.Column("target_url", sa.String(2048)),
        sa.Column("baseline_start", sa.Date(), nullable=False),
        sa.Column("baseline_end", sa.Date(), nullable=False),
        sa.Column("baseline_metrics", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("comparison_start", sa.Date()),
        sa.Column("comparison_end", sa.Date()),
        sa.Column("comparison_metrics", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("delta", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mutation_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("action_id", "window_days", name="uq_action_measurement_window"),
    )
    op.create_index("ix_action_measurements_workspace_status", "action_measurements", ["workspace_id", "status"])
    op.create_index(
        "ix_action_measurements_site_status_checked",
        "action_measurements",
        ["site_id", "status", "last_checked_at"],
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE job_queue
        SET status = 'failed',
            error_code = 'schema_downgrade',
            error_message = 'Search sync support was removed by schema downgrade',
            completed_at = COALESCE(completed_at, now()),
            lease_owner = NULL,
            lease_expires_at = NULL
        WHERE job_type = 'gsc_search_sync'
          AND status IN ('queued', 'running', 'retry_wait')
        """
    )
    op.drop_index("ix_action_measurements_site_status_checked", table_name="action_measurements")
    op.drop_index("ix_action_measurements_workspace_status", table_name="action_measurements")
    op.drop_table("action_measurements")
    op.drop_index("ix_search_opportunities_site_status", table_name="search_opportunities")
    op.drop_table("search_opportunities")
    op.drop_index("ix_search_metrics_workspace_date", table_name="search_analytics_metrics")
    op.drop_index("ix_search_metrics_site_date_page_key", table_name="search_analytics_metrics")
    op.drop_index("ix_search_metrics_site_date", table_name="search_analytics_metrics")
    op.drop_table("search_analytics_metrics")
    op.drop_index("ix_search_sync_attempts_job_id", table_name="search_sync_attempts")
    op.drop_table("search_sync_attempts")
    op.drop_index("uq_job_queue_active_gsc_sync_per_site", table_name="job_queue")
