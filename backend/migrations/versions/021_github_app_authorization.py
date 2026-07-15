"""Add GitHub App installations and authorized repository mappings.

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_app_installations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("repository_selection", sa.String(32), server_default="selected", nullable=False),
        sa.Column("permissions", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("installed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("installation_id", name="uq_github_app_installation_provider_id"),
    )
    op.create_index(
        "ix_github_app_installations_workspace_status",
        "github_app_installations",
        ["workspace_id", "status"],
    )
    op.create_table(
        "github_app_install_intents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_github_app_install_intents_workspace",
        "github_app_install_intents",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "github_repository_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "installation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("github_app_installations.id", ondelete="SET NULL"),
        ),
        sa.Column("github_repository_id", sa.BigInteger()),
        sa.Column("repository_full_name", sa.String(255), nullable=False),
        sa.Column("visibility", sa.String(32), server_default="public", nullable=False),
        sa.Column("default_branch", sa.String(255)),
        sa.Column("permissions", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("site_id", name="uq_github_repository_connection_site"),
    )
    op.create_index(
        "ix_github_repository_connections_workspace",
        "github_repository_connections",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_github_repository_connections_installation",
        "github_repository_connections",
        ["installation_id", "status"],
    )
    op.execute(
        """
        INSERT INTO github_repository_connections (
            workspace_id, site_id, repository_full_name, visibility, status
        )
        SELECT workspace_id, id, github_repo, 'public', 'active'
        FROM sites
        WHERE workspace_id IS NOT NULL AND github_repo IS NOT NULL
        ON CONFLICT (site_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_github_repository_connections_installation", table_name="github_repository_connections")
    op.drop_index("ix_github_repository_connections_workspace", table_name="github_repository_connections")
    op.drop_table("github_repository_connections")
    op.drop_index("ix_github_app_install_intents_workspace", table_name="github_app_install_intents")
    op.drop_table("github_app_install_intents")
    op.drop_index("ix_github_app_installations_workspace_status", table_name="github_app_installations")
    op.drop_table("github_app_installations")
