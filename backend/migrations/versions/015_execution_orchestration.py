"""Add durable operator action execution orchestration.

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_jobs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("action_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parent_job_id", UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["operator_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_job_id"], ["execution_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_execution_jobs_workspace_idempotency",
        ),
    )
    for name, columns in (
        ("ix_execution_jobs_action_id", ["action_id"]),
        ("ix_execution_jobs_workspace_id", ["workspace_id"]),
        ("ix_execution_jobs_site_id", ["site_id"]),
        ("ix_execution_jobs_job_type", ["job_type"]),
        ("ix_execution_jobs_status", ["status"]),
        ("ix_execution_jobs_queue", ["status", "run_after", "priority", "created_at"]),
    ):
        op.create_index(name, "execution_jobs", columns)
    op.create_index(
        "uq_execution_jobs_active_action_type",
        "execution_jobs",
        ["action_id", "job_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'retry_wait')"),
    )

    op.create_table(
        "execution_attempts",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["execution_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_execution_attempt_job_number"),
    )
    op.create_index("ix_execution_attempts_job_id", "execution_attempts", ["job_id"])

    op.create_table(
        "execution_snapshots",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("action_id", UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("external_revision", sa.String(length=255), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("data", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["operator_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["execution_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_execution_snapshots_action_id", ["action_id"]),
        ("ix_execution_snapshots_job_id", ["job_id"]),
        ("ix_execution_snapshots_workspace_id", ["workspace_id"]),
        ("ix_execution_snapshots_site_id", ["site_id"]),
        ("ix_execution_snapshots_snapshot_type", ["snapshot_type"]),
    ):
        op.create_index(name, "execution_snapshots", columns)

    op.execute(
        """
        CREATE FUNCTION prevent_execution_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'execution_snapshots is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER execution_snapshots_append_only
        BEFORE UPDATE OR DELETE ON execution_snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_execution_snapshot_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS execution_snapshots_append_only ON execution_snapshots")
    op.execute("DROP FUNCTION IF EXISTS prevent_execution_snapshot_mutation()")
    for name in (
        "ix_execution_snapshots_snapshot_type",
        "ix_execution_snapshots_site_id",
        "ix_execution_snapshots_workspace_id",
        "ix_execution_snapshots_job_id",
        "ix_execution_snapshots_action_id",
    ):
        op.drop_index(name, table_name="execution_snapshots")
    op.drop_table("execution_snapshots")

    op.drop_index("ix_execution_attempts_job_id", table_name="execution_attempts")
    op.drop_table("execution_attempts")

    op.drop_index("uq_execution_jobs_active_action_type", table_name="execution_jobs")
    for name in (
        "ix_execution_jobs_queue",
        "ix_execution_jobs_status",
        "ix_execution_jobs_job_type",
        "ix_execution_jobs_site_id",
        "ix_execution_jobs_workspace_id",
        "ix_execution_jobs_action_id",
    ):
        op.drop_index(name, table_name="execution_jobs")
    op.drop_table("execution_jobs")
