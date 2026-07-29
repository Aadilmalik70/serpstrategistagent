import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ContentOpportunity(Base):
    __tablename__ = "content_opportunities"
    __table_args__ = (
        UniqueConstraint("site_id", "opportunity_key", name="uq_content_opportunity_site_key"),
        Index("ix_content_opportunities_site_status_priority", "site_id", "status", "priority_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"))
    opportunity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", server_default="open", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    target_query: Mapped[str | None] = mapped_column(String(500))
    target_path: Mapped[str | None] = mapped_column(String(2048))
    priority_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    effort_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    briefs = relationship("ContentBrief", back_populates="opportunity")


class ContentBrief(Base):
    __tablename__ = "content_briefs"
    __table_args__ = (Index("ix_content_briefs_site_status_updated", "site_id", "status", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_opportunities.id", ondelete="SET NULL"))
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="draft", server_default="draft", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    target_query: Mapped[str | None] = mapped_column(String(500))
    search_intent: Mapped[str] = mapped_column(String(64), default="informational", server_default="informational", nullable=False)
    page_type: Mapped[str] = mapped_column(String(64), default="guide", server_default="guide", nullable=False)
    audience: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    business_goal: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    outline: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    required_topics: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    required_entities: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    internal_link_targets: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    faq_questions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    schema_recommendations: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    information_gain: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    scores: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    opportunity = relationship("ContentOpportunity", back_populates="briefs")
    drafts = relationship("ContentDraft", back_populates="brief", cascade="all, delete-orphan")


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    __table_args__ = (Index("ix_content_drafts_site_status_updated", "site_id", "status", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_briefs.id", ondelete="CASCADE"), nullable=False)
    action_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operator_actions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="draft", server_default="draft", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    meta_title: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    meta_description: Mapped[str] = mapped_column(String(1024), default="", server_default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(64), default="evidence_scaffold", server_default="evidence_scaffold", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    quality_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    brief = relationship("ContentBrief", back_populates="drafts")
    versions = relationship("ContentDraftVersion", back_populates="draft", cascade="all, delete-orphan")
    checks = relationship("ContentQualityCheck", back_populates="draft", cascade="all, delete-orphan")


class ContentDraftVersion(Base):
    __tablename__ = "content_draft_versions"
    __table_args__ = (UniqueConstraint("draft_id", "version", name="uq_content_draft_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    meta_title: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    meta_description: Mapped[str] = mapped_column(String(1024), default="", server_default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(64), default="manual", server_default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    draft = relationship("ContentDraft", back_populates="versions")


class ContentQualityCheck(Base):
    __tablename__ = "content_quality_checks"
    __table_args__ = (Index("ix_content_quality_checks_draft_created", "draft_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    passed: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    draft = relationship("ContentDraft", back_populates="checks")
