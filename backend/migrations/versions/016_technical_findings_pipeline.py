"""Normalize technical findings and link them to governed actions.

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("finding_type", sa.String(length=80), nullable=True))
    op.add_column("issues", sa.Column("fingerprint", sa.String(length=128), nullable=True))
    op.add_column("issues", sa.Column("detector_version", sa.String(length=32), nullable=True))
    op.add_column(
        "issues",
        sa.Column("evidence", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column("affected_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("issues", sa.Column("impact_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("issues", sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("issues", sa.Column("effort_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("issues", sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False))
    op.add_column("issues", sa.Column("regression_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("issues", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("issues", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("issues", sa.Column("source_crawl_id", UUID(as_uuid=True), nullable=True))

    op.execute(
        """
        UPDATE issues
        SET finding_type = COALESCE(NULLIF(meta->>'finding_type', ''), 'legacy_issue'),
            fingerprint = 'legacy:' || id::text,
            detector_version = 'legacy',
            evidence = jsonb_build_array(jsonb_build_object(
                'type', 'legacy_issue',
                'title', title,
                'severity', severity,
                'affected_url', affected_url
            )),
            affected_urls = CASE
                WHEN affected_url IS NULL OR affected_url = '' THEN '[]'::jsonb
                ELSE jsonb_build_array(affected_url)
            END,
            first_seen_at = created_at,
            last_seen_at = created_at
        """
    )

    op.alter_column("issues", "finding_type", existing_type=sa.String(length=80), nullable=False)
    op.alter_column("issues", "fingerprint", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("issues", "detector_version", existing_type=sa.String(length=32), nullable=False)
    op.alter_column("issues", "first_seen_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.alter_column("issues", "last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    op.create_foreign_key(
        "fk_issues_source_crawl",
        "issues",
        "crawl_snapshots",
        ["source_crawl_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_issues_site_fingerprint", "issues", ["site_id", "fingerprint"])
    op.create_index("ix_issues_site_status", "issues", ["site_id", "status"])
    op.create_index("ix_issues_finding_type", "issues", ["finding_type"])
    op.create_index("ix_issues_source_crawl_id", "issues", ["source_crawl_id"])


def downgrade() -> None:
    op.drop_index("ix_issues_source_crawl_id", table_name="issues")
    op.drop_index("ix_issues_finding_type", table_name="issues")
    op.drop_index("ix_issues_site_status", table_name="issues")
    op.drop_constraint("uq_issues_site_fingerprint", "issues", type_="unique")
    op.drop_constraint("fk_issues_source_crawl", "issues", type_="foreignkey")
    for column in (
        "source_crawl_id",
        "resolved_at",
        "last_seen_at",
        "first_seen_at",
        "regression_count",
        "occurrence_count",
        "effort_score",
        "confidence_score",
        "impact_score",
        "affected_urls",
        "evidence",
        "detector_version",
        "fingerprint",
        "finding_type",
    ):
        op.drop_column("issues", column)
