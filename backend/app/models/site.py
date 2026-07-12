import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=True
    )
    pending_claim_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", server_default="pending")

    # Ownership verification. workspace_id remains nullable only during the Phase 2 migration window.
    verification_status: Mapped[str] = mapped_column(
        String(32), default="unverified", server_default="unverified", nullable=False
    )
    verification_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Tech detection
    tech_stack: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cms: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Non-secret legacy metadata retained only for migration compatibility. All credentials
    # now live in encrypted IntegrationCredential records.
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wordpress_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wordpress_user: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Site context for content generation
    site_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace = relationship(
        "Workspace",
        back_populates="sites",
        foreign_keys=[workspace_id],
    )
    pending_claim_workspace = relationship(
        "Workspace",
        foreign_keys=[pending_claim_workspace_id],
    )
    integration_credentials = relationship(
        "IntegrationCredential", back_populates="site", cascade="all, delete-orphan"
    )
    pages = relationship("Page", back_populates="site", cascade="all, delete-orphan")
    crawl_snapshots = relationship("CrawlSnapshot", back_populates="site", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="site", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="site", cascade="all, delete-orphan")
    fix_actions = relationship("FixAction", back_populates="site", cascade="all, delete-orphan")

    @property
    def github_token(self) -> None:
        """Compatibility shim: plaintext GitHub tokens were permanently removed in migration 007."""
        return None

    @property
    def wordpress_app_password(self) -> None:
        """Compatibility shim: plaintext WordPress passwords were permanently removed in migration 007."""
        return None
