import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", server_default="pending")

    # Tech detection
    tech_stack: Mapped[str | None] = mapped_column(String(50), nullable=True)  # nextjs, react, wordpress, static
    cms: Mapped[str | None] = mapped_column(String(50), nullable=True)  # wordpress, ghost, none

    # GitHub integration
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)  # owner/repo
    github_token: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # WordPress integration
    wordpress_url: Mapped[str | None] = mapped_column(String(255), nullable=True)  # https://domain.com/wp-json
    wordpress_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wordpress_app_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Site context for content generation
    site_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    pages = relationship("Page", back_populates="site", cascade="all, delete-orphan")
    crawl_snapshots = relationship("CrawlSnapshot", back_populates="site", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="site", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="site", cascade="all, delete-orphan")
    fix_actions = relationship("FixAction", back_populates="site", cascade="all, delete-orphan")
