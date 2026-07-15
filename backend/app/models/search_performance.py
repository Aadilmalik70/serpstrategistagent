import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SearchAnalyticsMetric(Base):
    __tablename__ = "search_analytics_metrics"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "metric_date", "query_hash", "page_url_hash",
            name="uq_search_metric_site_date_query_page",
        ),
        Index("ix_search_metrics_site_date", "site_id", "metric_date"),
        Index("ix_search_metrics_site_date_page_key", "site_id", "metric_date", "page_url_key_hash"),
        Index("ix_search_metrics_workspace_date", "workspace_id", "metric_date"),
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
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    query: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_url: Mapped[str] = mapped_column(String(2048), default="", server_default="", nullable=False)
    page_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_url_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    clicks: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    impressions: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SearchOpportunity(Base):
    __tablename__ = "search_opportunities"
    __table_args__ = (
        UniqueConstraint("site_id", "opportunity_key", name="uq_search_opportunity_site_key"),
        Index("ix_search_opportunities_site_status", "site_id", "status", "priority_score"),
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
    opportunity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(String(2048))
    priority_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchSyncAttempt(Base):
    __tablename__ = "search_sync_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_search_sync_attempt_job_number"),
        Index("ix_search_sync_attempts_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_queue.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", server_default="running", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UrlInspectionResult(Base):
    __tablename__ = "url_inspection_results"
    __table_args__ = (
        UniqueConstraint("site_id", "url_hash", name="uq_url_inspection_site_url"),
        Index("ix_url_inspection_site_verdict", "site_id", "verdict", "inspected_at"),
        Index("ix_url_inspection_workspace_inspected", "workspace_id", "inspected_at"),
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
    inspection_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[str] = mapped_column(String(64), default="VERDICT_UNSPECIFIED", nullable=False)
    coverage_state: Mapped[str | None] = mapped_column(String(255))
    robots_txt_state: Mapped[str | None] = mapped_column(String(64))
    indexing_state: Mapped[str | None] = mapped_column(String(64))
    page_fetch_state: Mapped[str | None] = mapped_column(String(64))
    crawled_as: Mapped[str | None] = mapped_column(String(64))
    google_canonical: Mapped[str | None] = mapped_column(String(2048))
    user_canonical: Mapped[str | None] = mapped_column(String(2048))
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    referring_urls: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    sitemap_urls: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    raw_result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    first_inspected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inspected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UrlInspectionAttempt(Base):
    __tablename__ = "url_inspection_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_url_inspection_attempt_job_number"),
        Index("ix_url_inspection_attempts_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_queue.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", server_default="running", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionMeasurement(Base):
    __tablename__ = "action_measurements"
    __table_args__ = (
        UniqueConstraint("action_id", "window_days", name="uq_action_measurement_window"),
        Index("ix_action_measurements_workspace_status", "workspace_id", "status"),
        Index(
            "ix_action_measurements_site_status_checked",
            "site_id",
            "status",
            "last_checked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_actions.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="waiting", server_default="waiting", nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(32), default="insufficient_data", server_default="insufficient_data", nullable=False
    )
    target_query: Mapped[str | None] = mapped_column(Text)
    target_url: Mapped[str | None] = mapped_column(String(2048))
    baseline_start: Mapped[date] = mapped_column(Date, nullable=False)
    baseline_end: Mapped[date] = mapped_column(Date, nullable=False)
    baseline_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    comparison_start: Mapped[date | None] = mapped_column(Date)
    comparison_end: Mapped[date | None] = mapped_column(Date)
    comparison_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    delta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    mutation_applied: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    action = relationship("OperatorAction")
