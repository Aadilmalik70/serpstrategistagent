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


def upgrade() -> None:
    op.rename_table("fix_actions", "operator_actions")

    op.add_column("operator_actions", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.add_column("operator_actions", sa.Column("category", sa.String(length=64), server_default="technical", nullable=False))
    op.add_column("operator_actions", sa.Column("source", sa.String(length=64), server_default="legacy", nullable=False))
    op.add_column("operator_actions", sa.Column("evidence", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("impact_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("operator_actions", sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("operator_actions", sa.Column("effort_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("operator_actions", sa.Column("risk_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("operator_actions", sa.Column("risk_level", sa.String(length=16), server_default="low", nullable=False))
    op.add_column("operator_actions", sa.Column("approval_policy", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("requires_approval", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("operator_actions", sa.Column("execution_target", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("proposed_diff", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("rollback_plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("measurement_plan", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("validation_checklist", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("operator_actions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("operator_actions", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("operator_actions", sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True))
    op.add_column("operator_actions", sa.Column("approved_by_user_id", UUID(as_uuid=True), nullable=True))
    op.add_column("operator_actions", sa.Column("rejected_by_user_id", UUID(as_uuid=True), nullable=True))
    op.add_column("operator_actions", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("operator_actions", sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operator_actions", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operator_actions", sa.Column("rejection_reason", sa.String(length=1000), nullable=True))
    op.add_column("operator_actions", sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operator_actions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("operator_actions", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_operator_actions_workspace",
        "operator_actions",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_operator_actions_created_by",
        "operator_actions",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_operator_actions_approved_by",
        "operator_actions",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_operator_actions_rejected_by",
        "operator_actions",
        "users",
        ["rejected_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE operator_actions AS action
        SET workspace_id = site.workspace_id,
            source = 'legacy_fix_action',
            category = COALESCE(issue.category, 'technical'),
            evidence = CASE
                WHEN action.issue_id IS NULL THEN '[]'::jsonb
                ELSE jsonb_build_array(jsonb_build_object(
                    'type', 'legacy_issue',
                    'issue_id', action.issue_id::text,
                    'title', issue.title,
                    'severity', issue.severity,
                    'affected_url', issue.affected_url
                ))
            END,
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
        LEFT JOIN issues AS issue ON issue.id = action.issue_id
        WHERE site.id = action.site_id
        """
    )

    op.create_unique_constraint(
        "uq_operator_actions_workspace_idempotency",
        "operator_actions",
        ["workspace_id", "idempotency_key"],
    )
    op.create_index("ix_operator_actions_workspace_id", "operator_actions", ["workspace_id"])
    op.create_index("ix_operator_actions_site_id", "operator_actions", ["site_id"])
    op.create_index("ix_operator_actions_issue_id", "operator_actions", ["issue_id"])
    op.create_index("ix_operator_actions_status", "operator_actions", ["status"])
    op.create_index("ix_operator_actions_risk_level", "operator_actions", ["risk_level"])
    op.create_index(
        "ix_operator_actions_queue",
        "operator_actions",
        ["workspace_id", "status", "risk_level", "created_at"],
    )

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
    op.create_index("ix_operator_action_events_action_id", "operator_action_events", ["action_id"])
    op.create_index("ix_operator_action_events_workspace_id", "operator_action_events", ["workspace_id"])
    op.create_index("ix_operator_action_events_site_id", "operator_action_events", ["site_id"])
    op.create_index("ix_operator_action_events_event_type", "operator_action_events", ["event_type"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_operator_action_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'operator_action_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER operator_action_events_append_only
        BEFORE UPDATE OR DELETE ON operator_action_events
        FOR EACH ROW EXECUTE FUNCTION prevent_operator_action_event_mutation();
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
    op.drop_index("ix_operator_action_events_event_type", table_name="operator_action_events")
    op.drop_index("ix_operator_action_events_site_id", table_name="operator_action_events")
    op.drop_index("ix_operator_action_events_workspace_id", table_name="operator_action_events")
    op.drop_index("ix_operator_action_events_action_id", table_name="operator_action_events")
    op.drop_table("operator_action_events")

    op.drop_index("ix_operator_actions_queue", table_name="operator_actions")
    op.drop_index("ix_operator_actions_risk_level", table_name="operator_actions")
    op.drop_index("ix_operator_actions_status", table_name="operator_actions")
    op.drop_index("ix_operator_actions_issue_id", table_name="operator_actions")
    op.drop_index("ix_operator_actions_site_id", table_name="operator_actions")
    op.drop_index("ix_operator_actions_workspace_id", table_name="operator_actions")
    op.drop_constraint("uq_operator_actions_workspace_idempotency", "operator_actions", type_="unique")
    op.drop_constraint("fk_operator_actions_rejected_by", "operator_actions", type_="foreignkey")
    op.drop_constraint("fk_operator_actions_approved_by", "operator_actions", type_="foreignkey")
    op.drop_constraint("fk_operator_actions_created_by", "operator_actions", type_="foreignkey")
    op.drop_constraint("fk_operator_actions_workspace", "operator_actions", type_="foreignkey")

    for column in [
        "failed_at",
        "completed_at",
        "execution_started_at",
        "rejection_reason",
        "rejected_at",
        "proposed_at",
        "updated_at",
        "rejected_by_user_id",
        "approved_by_user_id",
        "created_by_user_id",
        "version",
        "idempotency_key",
        "validation_checklist",
        "measurement_plan",
        "rollback_plan",
        "proposed_diff",
        "execution_target",
        "requires_approval",
        "approval_policy",
        "risk_level",
        "risk_score",
        "effort_score",
        "confidence_score",
        "impact_score",
        "plan",
        "evidence",
        "source",
        "category",
        "workspace_id",
    ]:
        op.drop_column("operator_actions", column)

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
    op.rename_table("operator_actions", "fix_actions")
