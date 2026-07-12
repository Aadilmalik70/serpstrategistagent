import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GoogleDataConnection(Base):
    __tablename__ = "google_data_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_google_data_workspace_user"),
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
    encrypted_tokens: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    oauth_state_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="not_connected", server_default="not_connected", nullable=False
    )
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    gsc_property: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ga4_property_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ga4_property_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    baseline_status: Mapped[str] = mapped_column(
        String(32), default="not_started", server_default="not_started", nullable=False
    )
    baseline_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace = relationship("Workspace")
    user = relationship("User")
