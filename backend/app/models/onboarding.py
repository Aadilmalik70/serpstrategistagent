import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OnboardingState(Base):
    __tablename__ = "onboarding_states"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_onboarding_workspace_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    onboarding_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), default="profile", server_default="profile", nullable=False)
    completed_steps: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", server_default="in_progress", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace")
    user = relationship("User")
