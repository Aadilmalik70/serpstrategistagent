"""Normalize legacy fix actions into governed operator actions.

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


ACTION_COLUMNS = [
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=True),
    sa.Column("category", sa.String(length=64), server_default="technical", nullable=False),
    sa.Column("source", sa.String(length=64), server_default="legacy", nullable=False),
    sa.Column("evidence", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column("plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("impact_score", sa.Integer(), server_default="0", nullable=False),
    sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False),
    sa.Column("effort_score", sa.Integer(), server_default="0", nullable=False),
    sa.Column("risk_score", sa.Integer(), server_default="0", nullable=False),
    sa.Column("risk_level", sa.String(length=16), server_default="low", nullable=False),
    sa.Column("approval_policy", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("requires_approval", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    sa.Column("execution_target", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("proposed_diff", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("rollback_plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("measurement_plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("validation_checklist", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
    sa.Column("approved_by_user_id", UUID(as_uuid=True), nullable=True),
    sa.Column("rejected_by_user_id", UUID(as_uuid=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("rejection_reason", sa.String(length=1000), nullable=True),
    sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    op.rename_table("fix_actions", "operator_actions")

    # A governed action can originate from Search Console, GA4, a public audit,
    # a manual operator plan, or a future detector without a legacy Issue row.
    op.alter_column(
        "operator_actions",
        "issue_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )

    for column in ACTION_COLUMNS:
        op.add_column("operator_actions", column)

    for name, column in (
        ("fk_operator_actions_workspace", "workspace_id"),
        ("fk_operator_actions_created_by", "created_by_user_id"),
        ("fk_operator_actions_approved_by", "approved_by_user_id"),
        ("fk_operator_actions_rejected_by", "rejected_by_user_id"),
    ):
        target = "workspaces" if column == "workspace_id" else "users"
        op.create_foreign_key(
            name,
            "operator_actions",
            target,
            [column],
            ["id"],
            ondelete="CASCADE" if column == "workspace_id" else "SET NULL",
        )

    # PostgreSQL does not allow the UPDATE target alias to be referenced inside
    # a JOIN's ON clause. Backfill site-owned fields first, then issue evidence.
    op.execute(
        """
        UPDATE operator_actions AS action
        SET workspace_id = site.workspace_id,
            source = 'legacy_fix_action',
            plan = COALESCE(action.fix_content, '{}'::jsonb),
            risk_level = COALESCE(action.fix_content->'governance'->>'risk_level', 'medium'),
            requires_approval = COALESCE(
                (action.fix_content->'governance'->>'requires_human_approval')::boolean,
                true
            ),
            status = CASE action.status
                WHEN 'pending' THEN 'draft'
                WHEN 'completed' THEN 'succeeded'
                ELSE action.status
            END,
            proposed_at = CASE WHEN action.status <> 'pending' THEN action.created_at ELSE NULL END,
            completed_at = CASE WHEN action.status = 'completed' THEN action.executed_at ELSE NULL END,
            failed_at = CASE WHEN action.status = 'failed' THEN action.executed_at ELSE NULL END
        FROM sites AS site
        WHERE site.id = action.site_id
        """
    )
    op.execute(
        """
        UPDATE operator_actions AS action
        SET category = issue.category,
            evidence = jsonb_build_array(jsonb_build_object(
                'type', 'legacy_issue',
                'issue_id', issue.id::text,
                'title', issue.title,
                'severity', issue.severity,
                'affected_url', issue.affected_url
            ))
        FROM issues AS issue
        WHERE issue.id = action.issue_id
        """
    )

    op.create_unique_constraint(
        "uq_operator_actions_workspace_idempotency",
        "operator_actions",
        ["workspace_id", "idempotency_key"],
    )
    for name, columns in (
        ("ix_operator_actions_workspace_id", ["workspace_id"]),
        ("ix_operator_actions_site_id", ["site_id"]),
        ("ix_operator_actions_issue_id", ["issue_id"]),
        ("ix_operator_actions_status", ["status"]),
        ("ix_operator_actions_risk_level", ["risk_level"]),
        ("ix_operator_actions_queue", ["workspace_id", "status", "risk_level", "created_at"]),
    ):
        op.create_index(name, "operator_actions", columns)

    op.create_table(
        "operator_action_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("action_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=32), server_default="user", nullable=False),
        sa.Column("payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["operator_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_operator_action_events_action_id", ["action_id"]),
        ("ix_operator_action_events_workspace_id", ["workspace_id"]),
        ("ix_operator_action_events_site_id", ["site_id"]),
        ("ix_operator_action_events_event_type", ["event_type"]),
    ):
        op.create_index(name, "operator_action_events", columns)

    op.execute(
        """
        CREATE FUNCTION prevent_operator_action_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'operator_action_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER operator_action_events_append_only
        BEFORE UPDATE OR DELETE ON operator_action_events
        FOR EACH ROW EXECUTE FUNCTION prevent_operator_action_event_mutation()
        """
    )
    op.execute(
        """
        INSERT INTO operator_action_events (
            action_id, workspace_id, site_id, event_type, from_status, to_status, actor_type, payload
        )
        SELECT id, workspace_id, site_id, 'legacy_action_migrated', NULL, status, 'system',
               jsonb_build_object('legacy_status', status)
        FROM operator_actions
        WHERE workspace_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS operator_action_events_append_only ON operator_action_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_operator_action_event_mutation()")
    for name in (
        "ix_operator_action_events_event_type",
        "ix_operator_action_events_site_id",
        "ix_operator_action_events_workspace_id",
        "ix_operator_action_events_action_id",
    ):
        op.drop_index(name, table_name="operator_action_events")
    op.drop_table("operator_action_events")

    for name in (
        "ix_operator_actions_queue",
        "ix_operator_actions_risk_level",
        "ix_operator_actions_status",
        "ix_operator_actions_issue_id",
        "ix_operator_actions_site_id",
        "ix_operator_actions_workspace_id",
    ):
        op.drop_index(name, table_name="operator_actions")
    op.drop_constraint("uq_operator_actions_workspace_idempotency", "operator_actions", type_="unique")
    for name in (
        "fk_operator_actions_rejected_by",
        "fk_operator_actions_approved_by",
        "fk_operator_actions_created_by",
        "fk_operator_actions_workspace",
    ):
        op.drop_constraint(name, "operator_actions", type_="foreignkey")

    for column in reversed(ACTION_COLUMNS):
        op.drop_column("operator_actions", column.name)
    op.execute(
        """
        UPDATE operator_actions
        SET status = CASE status
            WHEN 'draft' THEN 'pending'
            WHEN 'succeeded' THEN 'completed'
            ELSE status
        END
        """
    )

    # Legacy fix_actions required an issue. Actions created from newer evidence
    # sources cannot be represented in that schema and are removed on downgrade.
    op.execute("DELETE FROM operator_actions WHERE issue_id IS NULL")
    op.alter_column(
        "operator_actions",
        "issue_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
    op.rename_table("operator_actions", "fix_actions")
