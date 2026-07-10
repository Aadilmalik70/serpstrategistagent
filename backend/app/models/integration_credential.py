import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "site_id",
            "provider",
            "external_account_id",
            name="uq_integration_credential_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True, nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), default="default", server_default="default", nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(32), default="v1", server_default="v1", nullable=False)
    credential_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active", nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace = relationship("Workspace", back_populates="integration_credentials")
    site = relationship("Site", back_populates="integration_credentials")
