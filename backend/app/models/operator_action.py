import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OperatorAction(Base):
    __tablename__ = "operator_actions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_operator_actions_workspace_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="SET NULL"), index=True, nullable=True
    )

    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="technical", server_default="technical", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="operator", server_default="operator", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", server_default="draft", index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    plan: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    impact_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    effort_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", server_default="low", index=True, nullable=False)

    approval_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    execution_target: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    proposed_diff: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    rollback_plan: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    measurement_plan: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    validation_checklist: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)

    # Legacy compatibility fields retained while planners migrate to the normalized shape.
    fix_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    execution_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    site = relationship("Site", back_populates="fix_actions")
    issue = relationship("Issue", back_populates="fix_actions")
    events = relationship(
        "OperatorActionEvent",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="OperatorActionEvent.created_at",
    )


class OperatorActionEvent(Base):
    __tablename__ = "operator_action_events"

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
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), default="user", server_default="user", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    action = relationship("OperatorAction", back_populates="events")
