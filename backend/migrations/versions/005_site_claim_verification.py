"""Add pending workspace ownership claim fields.

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("pending_claim_workspace_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sites_pending_claim_workspace_id_workspaces",
        "sites",
        "workspaces",
        ["pending_claim_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sites_pending_claim_workspace_id",
        "sites",
        ["pending_claim_workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sites_pending_claim_workspace_id", table_name="sites")
    op.drop_constraint(
        "fk_sites_pending_claim_workspace_id_workspaces",
        "sites",
        type_="foreignkey",
    )
    op.drop_column("sites", "verification_expires_at")
    op.drop_column("sites", "pending_claim_workspace_id")
