import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_execution_jobs_workspace_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_actions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="SET NULL"), nullable=True
    )

    job_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued", index=True, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)

    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts = relationship(
        "ExecutionAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ExecutionAttempt.attempt_number",
    )
    snapshots = relationship(
        "ExecutionSnapshot",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ExecutionSnapshot.created_at",
    )


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_execution_attempt_job_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job = relationship("ExecutionJob", back_populates="attempts")


class ExecutionSnapshot(Base):
    __tablename__ = "execution_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_actions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    snapshot_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    external_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("ExecutionJob", back_populates="snapshots")
