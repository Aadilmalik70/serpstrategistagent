"""Add secure integration lifecycle fields and remove plaintext site secrets.

Revision ID: 007
Revises: 006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integration_credentials", sa.Column("scope_key", sa.String(length=64), nullable=True))
    op.add_column("integration_credentials", sa.Column("label", sa.String(length=255), nullable=True))
    op.add_column(
        "integration_credentials",
        sa.Column(
            "last_validation_status",
            sa.String(length=32),
            server_default="not_tested",
            nullable=False,
        ),
    )
    op.add_column(
        "integration_credentials",
        sa.Column("last_validation_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "integration_credentials",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_credentials",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_credentials",
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "integration_credentials",
        sa.Column("updated_by_user_id", UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        UPDATE integration_credentials
        SET scope_key = COALESCE(site_id::text, 'workspace'),
            label = INITCAP(REPLACE(provider, '_', ' '))
        """
    )
    op.alter_column("integration_credentials", "scope_key", nullable=False)
    op.alter_column("integration_credentials", "label", nullable=False)

    op.drop_constraint(
        "uq_integration_credential_scope",
        "integration_credentials",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_integration_credential_scope_v2",
        "integration_credentials",
        ["workspace_id", "scope_key", "provider", "external_account_id"],
    )
    op.create_index(
        "ix_integration_credentials_scope_key",
        "integration_credentials",
        ["scope_key"],
    )
    op.create_foreign_key(
        "fk_integration_credentials_created_by_user",
        "integration_credentials",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_integration_credentials_updated_by_user",
        "integration_credentials",
        "users",
        ["updated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Existing prototype secrets cannot be safely encrypted inside a SQL migration.
    # Invalidate and remove them; users reconnect through the encrypted integration UI.
    op.execute("UPDATE sites SET github_token = NULL, wordpress_app_password = NULL")
    op.drop_column("sites", "github_token")
    op.drop_column("sites", "wordpress_app_password")


def downgrade() -> None:
    op.add_column("sites", sa.Column("wordpress_app_password", sa.String(length=255), nullable=True))
    op.add_column("sites", sa.Column("github_token", sa.String(length=255), nullable=True))

    op.drop_constraint(
        "fk_integration_credentials_updated_by_user",
        "integration_credentials",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_integration_credentials_created_by_user",
        "integration_credentials",
        type_="foreignkey",
    )
    op.drop_index("ix_integration_credentials_scope_key", table_name="integration_credentials")
    op.drop_constraint(
        "uq_integration_credential_scope_v2",
        "integration_credentials",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_integration_credential_scope",
        "integration_credentials",
        ["workspace_id", "site_id", "provider", "external_account_id"],
    )

    op.drop_column("integration_credentials", "updated_by_user_id")
    op.drop_column("integration_credentials", "created_by_user_id")
    op.drop_column("integration_credentials", "revoked_at")
    op.drop_column("integration_credentials", "rotated_at")
    op.drop_column("integration_credentials", "last_validation_error")
    op.drop_column("integration_credentials", "last_validation_status")
    op.drop_column("integration_credentials", "label")
    op.drop_column("integration_credentials", "scope_key")
