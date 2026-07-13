"""Add public free audit requests.

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
        "free_audit_requests",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("summary", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("findings", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("requester_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_token"),
    )
    op.create_index("ix_free_audit_requests_public_token", "free_audit_requests", ["public_token"], unique=True)
    op.create_index("ix_free_audit_requests_email", "free_audit_requests", ["email"])
    op.create_index("ix_free_audit_requests_domain", "free_audit_requests", ["domain"])
    op.create_index("ix_free_audit_requests_status", "free_audit_requests", ["status"])
    op.create_index("ix_free_audit_requests_requester_hash", "free_audit_requests", ["requester_hash"])


def downgrade() -> None:
    op.drop_index("ix_free_audit_requests_requester_hash", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_requests_status", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_requests_domain", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_requests_email", table_name="free_audit_requests")
    op.drop_index("ix_free_audit_requests_public_token", table_name="free_audit_requests")
    op.drop_table("free_audit_requests")
