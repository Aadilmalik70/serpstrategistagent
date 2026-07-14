"""Persist free-audit claims and operator handoff ownership.

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "free_audit_requests",
        sa.Column("claimed_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "free_audit_requests",
        sa.Column("claimed_workspace_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "free_audit_requests",
        sa.Column("claimed_site_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "free_audit_requests",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_free_audit_claimed_user",
        "free_audit_requests",
        "users",
        ["claimed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_free_audit_claimed_workspace",
        "free_audit_requests",
        "workspaces",
        ["claimed_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_free_audit_claimed_site",
        "free_audit_requests",
        "sites",
        ["claimed_site_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_free_audit_claimed_by_user_id",
        "free_audit_requests",
        ["claimed_by_user_id"],
    )
    op.create_index(
        "ix_free_audit_claimed_workspace_id",
        "free_audit_requests",
        ["claimed_workspace_id"],
    )
    op.create_index(
        "ix_free_audit_claimed_site_id",
        "free_audit_requests",
        ["claimed_site_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_free_audit_claimed_site_id", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_claimed_workspace_id", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_claimed_by_user_id", table_name="free_audit_requests")
    op.drop_constraint("fk_free_audit_claimed_site", "free_audit_requests", type_="foreignkey")
    op.drop_constraint("fk_free_audit_claimed_workspace", "free_audit_requests", type_="foreignkey")
    op.drop_constraint("fk_free_audit_claimed_user", "free_audit_requests", type_="foreignkey")
    op.drop_column("free_audit_requests", "claimed_at")
    op.drop_column("free_audit_requests", "claimed_site_id")
    op.drop_column("free_audit_requests", "claimed_workspace_id")
    op.drop_column("free_audit_requests", "claimed_by_user_id")
