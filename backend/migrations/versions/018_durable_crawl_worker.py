"""Add durable crawl worker leases, attempts, and URL frontier.

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_queue", sa.Column("priority", sa.Integer(), server_default="0", nullable=False))
    op.add_column("job_queue", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("job_queue", sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False))
    op.add_column("job_queue", sa.Column("error_code", sa.String(length=100), nullable=True))
    op.add_column("job_queue", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column(
        "job_queue",
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("job_queue", sa.Column("lease_owner", sa.String(length=255), nullable=True))
    op.add_column("job_queue", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_queue", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "job_queue",
        sa.Column("cancellation_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "job_queue",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # A deployment can interrupt an older in-process crawl. Requeue it so the
    # durable worker claims it instead of leaving it permanently running.
    op.execute(
        """
        UPDATE job_queue AS job
        SET payload = COALESCE(job.payload, '{}'::jsonb)
            || jsonb_build_object('workspace_id', site.workspace_id::text)
        FROM sites AS site
        WHERE job.site_id = site.id
          AND job.job_type = 'crawl'
          AND site.workspace_id IS NOT NULL
          AND NOT (COALESCE(job.payload, '{}'::jsonb) ? 'workspace_id')
        """
    )
    op.execute(
        """
        UPDATE job_queue
        SET status = 'retry_wait', run_after = now(), lease_owner = NULL,
            lease_expires_at = NULL, heartbeat_at = NULL
        WHERE job_type = 'crawl' AND status = 'running'
        """
    )
    op.execute(
        """
        UPDATE job_queue
        SET status = 'queued', run_after = now()
        WHERE job_type = 'crawl' AND status = 'pending'
        """
    )
    # Older API background tasks could create more than one active crawl for a
    # site. Preserve the newest and close the rest before enforcing the durable
    # singleton invariant.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY site_id
                       ORDER BY created_at DESC, id DESC
                   ) AS active_rank
            FROM job_queue
            WHERE job_type = 'crawl'
              AND status IN ('queued', 'running', 'retry_wait')
        )
        UPDATE job_queue AS job
        SET status = 'cancelled',
            error_code = 'duplicate_superseded',
            error_message = 'Superseded during durable crawl queue migration',
            completed_at = now(),
            lease_owner = NULL,
            lease_expires_at = NULL,
            heartbeat_at = NULL
        FROM ranked
        WHERE job.id = ranked.id AND ranked.active_rank > 1
        """
    )

    op.create_index(
        "ix_job_queue_claim",
        "job_queue",
        ["job_type", "status", "run_after", "priority", "created_at"],
    )
    op.create_index("ix_job_queue_lease_expires_at", "job_queue", ["lease_expires_at"])
    op.create_index(
        "uq_job_queue_active_crawl_per_site",
        "job_queue",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'crawl' AND status IN ('queued', 'running', 'retry_wait')"
        ),
    )

    op.create_table(
        "crawl_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_queue.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="running", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_crawl_attempt_job_number"),
    )
    op.create_index("ix_crawl_attempts_job_id", "crawl_attempts", ["job_id"])

    op.create_table(
        "crawl_frontier",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_queue.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("discovered_from", sa.String(length=2048), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", "url_hash", name="uq_crawl_frontier_job_url_hash"),
    )
    op.create_index("ix_crawl_frontier_job_status", "crawl_frontier", ["job_id", "status", "created_at"])


def downgrade() -> None:
    # A rollback cannot preserve worker-only retry/lease state. Operators must
    # disable and drain the worker first; this normalization prevents the old
    # in-process runtime from inheriting permanently stuck active records.
    op.execute(
        """
        UPDATE job_queue
        SET status = 'failed',
            error_code = 'durable_worker_rollback',
            error_message = 'Crawl stopped because the durable worker schema was rolled back',
            completed_at = now()
        WHERE job_type = 'crawl'
          AND status IN ('queued', 'running', 'retry_wait')
        """
    )
    op.execute(
        """
        UPDATE sites
        SET status = 'crawl_failed'
        WHERE status IN ('crawl_queued', 'crawling')
        """
    )
    op.drop_index("ix_crawl_frontier_job_status", table_name="crawl_frontier")
    op.drop_table("crawl_frontier")
    op.drop_index("ix_crawl_attempts_job_id", table_name="crawl_attempts")
    op.drop_table("crawl_attempts")
    op.drop_index("uq_job_queue_active_crawl_per_site", table_name="job_queue")
    op.drop_index("ix_job_queue_lease_expires_at", table_name="job_queue")
    op.drop_index("ix_job_queue_claim", table_name="job_queue")
    op.drop_column("job_queue", "updated_at")
    op.drop_column("job_queue", "cancellation_requested")
    op.drop_column("job_queue", "heartbeat_at")
    op.drop_column("job_queue", "lease_expires_at")
    op.drop_column("job_queue", "lease_owner")
    op.drop_column("job_queue", "run_after")
    op.drop_column("job_queue", "error_message")
    op.drop_column("job_queue", "error_code")
    op.drop_column("job_queue", "max_attempts")
    op.drop_column("job_queue", "attempt_count")
    op.drop_column("job_queue", "priority")
