import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContentInsight(Base):
    __tablename__ = "content_insights"
    __table_args__ = (
        UniqueConstraint("site_id", "page_id", name="uq_content_insights_site_page"),
        Index("ix_content_insights_site_decay", "site_id", "decay_score"),
        Index("ix_content_insights_site_analyzed", "site_id", "analyzed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    content_age_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    freshness_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    decay_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    information_gain_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    topics: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    entities: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    unique_terms: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InternalLinkRecommendation(Base):
    __tablename__ = "internal_link_recommendations"
    __table_args__ = (
        UniqueConstraint("site_id", "recommendation_key", name="uq_internal_link_recommendation_key"),
        Index("ix_internal_link_recommendations_site_status", "site_id", "status", "priority_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    source_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    target_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    recommendation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    anchor_text: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
