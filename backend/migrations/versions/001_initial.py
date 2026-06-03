"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sites table
    op.create_table(
        "sites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Pages table
    op.create_table(
        "pages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("meta_description", sa.String(1024)),
        sa.Column("h1", sa.String(512)),
        sa.Column("status_code", sa.Integer),
        sa.Column("word_count", sa.Integer),
        sa.Column("response_time_ms", sa.Integer),
        sa.Column("canonical_url", sa.String(2048)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("meta", JSONB),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "path", name="uq_site_path"),
    )
    op.create_index("ix_pages_site_id", "pages", ["site_id"])

    # Crawl Snapshots table
    op.create_table(
        "crawl_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), server_default="running"),
        sa.Column("pages_discovered", sa.Integer, server_default="0"),
        sa.Column("pages_crawled", sa.Integer, server_default="0"),
        sa.Column("errors", sa.Integer, server_default="0"),
        sa.Column("extracted_data", JSONB),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_crawl_snapshots_site_id", "crawl_snapshots", ["site_id"])

    # Job Queue table
    op.create_table(
        "job_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("payload", JSONB),
        sa.Column("result", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_job_queue_site_id", "job_queue", ["site_id"])
    op.create_index("ix_job_queue_status", "job_queue", ["status"])


def downgrade() -> None:
    op.drop_table("job_queue")
    op.drop_table("crawl_snapshots")
    op.drop_table("pages")
    op.drop_table("sites")
