import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobQueue(Base):
    __tablename__ = "job_queue"
    __table_args__ = (
        Index(
            "ix_job_queue_claim",
            "job_type",
            "status",
            "run_after",
            "priority",
            "created_at",
        ),
        Index("ix_job_queue_lease_expires_at", "lease_expires_at"),
        Index(
            "uq_job_queue_active_crawl_per_site",
            "site_id",
            unique=True,
            postgresql_where=text(
                "job_type = 'crawl' AND status IN ('queued', 'running', 'retry_wait')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "crawl", "analyze", etc.
    status: Mapped[str] = mapped_column(String(50), default="pending", server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempts = relationship(
        "CrawlAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CrawlAttempt.attempt_number",
    )
    frontier = relationship(
        "CrawlFrontier",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class CrawlAttempt(Base):
    __tablename__ = "crawl_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_crawl_attempt_job_number"),
        Index("ix_crawl_attempts_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_queue.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", server_default="running")
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job = relationship("JobQueue", back_populates="attempts")


class CrawlFrontier(Base):
    __tablename__ = "crawl_frontier"
    __table_args__ = (
        UniqueConstraint("job_id", "url_hash", name="uq_crawl_frontier_job_url_hash"),
        Index("ix_crawl_frontier_job_status", "job_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_queue.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="queued", server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    discovered_from: Mapped[str | None] = mapped_column(String(2048))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job = relationship("JobQueue", back_populates="frontier")
