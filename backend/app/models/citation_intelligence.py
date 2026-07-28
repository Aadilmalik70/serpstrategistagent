import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CitationPromptSet(Base):
    __tablename__ = "citation_prompt_sets"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_citation_prompt_set_site_name"),
        Index("ix_citation_prompt_sets_site_status", "site_id", "status", "updated_at"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_terms: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    competitor_terms: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    prompts: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    providers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    schedule_interval_hours: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    scans = relationship("CitationScan", back_populates="prompt_set", cascade="all, delete-orphan")


class CitationScan(Base):
    __tablename__ = "citation_scans"
    __table_args__ = (
        Index("ix_citation_scans_site_status_created", "site_id", "status", "created_at"),
        Index("ix_citation_scans_workspace_created", "workspace_id", "created_at"),
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
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citation_prompt_sets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", server_default="queued", nullable=False)
    providers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    prompt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    visibility_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    mention_rate: Mapped[float] = mapped_column(server_default="0", nullable=False)
    citation_rate: Mapped[float] = mapped_column(server_default="0", nullable=False)
    competitor_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    prompt_set = relationship("CitationPromptSet", back_populates="scans")
    results = relationship("CitationResult", back_populates="scan", cascade="all, delete-orphan")
    gaps = relationship("CitationGap", back_populates="scan", cascade="all, delete-orphan")


class CitationResult(Base):
    __tablename__ = "citation_results"
    __table_args__ = (
        UniqueConstraint("scan_id", "provider", "prompt_hash", name="uq_citation_result_scan_provider_prompt"),
        Index("ix_citation_results_scan_provider", "scan_id", "provider"),
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
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citation_scans.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer_excerpt: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    brand_mentioned: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    cited_urls: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    competitor_mentions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    scan = relationship("CitationScan", back_populates="results")


class CitationGap(Base):
    __tablename__ = "citation_gaps"
    __table_args__ = (
        UniqueConstraint("site_id", "gap_key", name="uq_citation_gap_site_key"),
        Index("ix_citation_gaps_site_status_priority", "site_id", "status", "priority_score"),
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
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citation_scans.id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_actions.id", ondelete="SET NULL")
    )
    gap_key: Mapped[str] = mapped_column(String(128), nullable=False)
    gap_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    competitor: Mapped[str | None] = mapped_column(String(255))
    priority_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scan = relationship("CitationScan", back_populates="gaps")
