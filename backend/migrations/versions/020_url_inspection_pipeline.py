"""Add durable Search Console URL Inspection state.

Revision ID: 020
Revises: 019
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_job_queue_active_url_inspection_per_site",
        "job_queue",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'gsc_url_inspection' AND status IN ('queued', 'running', 'retry_wait')"
        ),
    )
    op.create_table(
        "url_inspection_attempts",
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
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_url_inspection_attempt_job_number"),
    )
    op.create_index("ix_url_inspection_attempts_job_id", "url_inspection_attempts", ["job_id"])

    op.create_table(
        "url_inspection_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inspection_url", sa.String(2048), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(64), server_default="VERDICT_UNSPECIFIED", nullable=False),
        sa.Column("coverage_state", sa.String(255)),
        sa.Column("robots_txt_state", sa.String(64)),
        sa.Column("indexing_state", sa.String(64)),
        sa.Column("page_fetch_state", sa.String(64)),
        sa.Column("crawled_as", sa.String(64)),
        sa.Column("google_canonical", sa.String(2048)),
        sa.Column("user_canonical", sa.String(2048)),
        sa.Column("last_crawl_time", sa.DateTime(timezone=True)),
        sa.Column("referring_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("sitemap_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("raw_result", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("first_inspected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("inspected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("site_id", "url_hash", name="uq_url_inspection_site_url"),
    )
    op.create_index(
        "ix_url_inspection_site_verdict",
        "url_inspection_results",
        ["site_id", "verdict", "inspected_at"],
    )
    op.create_index(
        "ix_url_inspection_workspace_inspected",
        "url_inspection_results",
        ["workspace_id", "inspected_at"],
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE job_queue
        SET status = 'failed',
            error_code = 'schema_downgrade',
            error_message = 'URL Inspection support was removed by schema downgrade',
            completed_at = COALESCE(completed_at, now()),
            lease_owner = NULL,
            lease_expires_at = NULL
        WHERE job_type = 'gsc_url_inspection'
          AND status IN ('queued', 'running', 'retry_wait')
        """
    )
    op.drop_index("ix_url_inspection_workspace_inspected", table_name="url_inspection_results")
    op.drop_index("ix_url_inspection_site_verdict", table_name="url_inspection_results")
    op.drop_table("url_inspection_results")
    op.drop_index("ix_url_inspection_attempts_job_id", table_name="url_inspection_attempts")
    op.drop_table("url_inspection_attempts")
    op.drop_index("uq_job_queue_active_url_inspection_per_site", table_name="job_queue")
