"""Add GitHub App installations and site mappings.

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_app_installations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("installed_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=64), nullable=True),
        sa.Column("repository_selection", sa.String(length=32), nullable=True),
        sa.Column("permissions", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "installation_id", name="uq_github_installation_workspace"),
    )
    op.create_index("ix_github_app_installations_workspace_id", "github_app_installations", ["workspace_id"])
    op.create_index("ix_github_app_installations_installation_id", "github_app_installations", ["installation_id"])

    op.create_table(
        "github_app_install_intents",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index("ix_github_app_install_intents_workspace_id", "github_app_install_intents", ["workspace_id"])

    op.add_column("sites", sa.Column("github_app_installation_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_sites_github_app_installation_id", "sites", ["github_app_installation_id"])
    op.create_foreign_key(
        "fk_sites_github_app_installation",
        "sites",
        "github_app_installations",
        ["github_app_installation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sites_github_app_installation", "sites", type_="foreignkey")
    op.drop_index("ix_sites_github_app_installation_id", table_name="sites")
    op.drop_column("sites", "github_app_installation_id")
    op.drop_index("ix_github_app_install_intents_workspace_id", table_name="github_app_install_intents")
    op.drop_table("github_app_install_intents")
    op.drop_index("ix_github_app_installations_installation_id", table_name="github_app_installations")
    op.drop_index("ix_github_app_installations_workspace_id", table_name="github_app_installations")
    op.drop_table("github_app_installations")
