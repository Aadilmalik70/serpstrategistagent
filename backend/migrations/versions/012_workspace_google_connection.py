"""Scope Google data connections to one record per workspace.

Revision ID: 012
Revises: 011
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the most recently updated connection when an early build created
    # more than one user-scoped record for the same workspace.
    op.execute(
        """
        DELETE FROM google_data_connections older
        USING google_data_connections newer
        WHERE older.workspace_id = newer.workspace_id
          AND (
            older.updated_at < newer.updated_at
            OR (older.updated_at = newer.updated_at AND older.id::text < newer.id::text)
          )
        """
    )
    op.drop_constraint(
        "uq_google_data_workspace_user",
        "google_data_connections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_google_data_workspace",
        "google_data_connections",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_google_data_workspace",
        "google_data_connections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_google_data_workspace_user",
        "google_data_connections",
        ["workspace_id", "user_id"],
    )
