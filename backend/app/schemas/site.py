import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("Invalid domain format")
    return parsed.netloc


class SiteCreate(BaseModel):
    domain: str
    name: str | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalize_domain(value)


class SiteDomainRequest(BaseModel):
    domain: str

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalize_domain(value)


class SiteClaimVerifyRequest(SiteDomainRequest):
    token: str = Field(min_length=20, max_length=256)


class SiteClaimStartResponse(BaseModel):
    site_id: uuid.UUID
    domain: str
    method: str
    record_name: str
    record_value: str
    expires_at: datetime


class SiteResponse(BaseModel):
    id: uuid.UUID
    domain: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LatestRunInfo(BaseModel):
    id: uuid.UUID
    status: str
    pages_analyzed: int = 0
    issues_found: int = 0
    summary: str | None = None
    completed_at: datetime | None = None


class SiteDetailResponse(SiteResponse):
    page_count: int = 0
    issue_count: int = 0
    last_crawled_at: datetime | None = None
    tech_stack: str | None = None
    cms: str | None = None
    github_connected: bool = False
    wordpress_connected: bool = False
    health_score: int | None = None
    health_grade: str | None = None
    latest_run: LatestRunInfo | None = None
    librecrawl_enabled: bool = False
