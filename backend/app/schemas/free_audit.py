import uuid
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field, field_validator


class FreeAuditCreate(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    website: str = Field(min_length=4, max_length=2048)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid work email")
        return normalized

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            normalized = f"https://{normalized}"
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Enter a valid website URL")
        if parsed.username or parsed.password:
            raise ValueError("Website URL cannot contain credentials")
        clean = parsed._replace(fragment="")
        return urlunparse(clean)


class FreeAuditFinding(BaseModel):
    code: str
    title: str
    severity: str
    description: str
    evidence: str | None = None


class FreeAuditResponse(BaseModel):
    token: str
    status: str
    website: str
    domain: str
    score: int | None
    summary: dict
    findings: list[FreeAuditFinding]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    retry_after_seconds: int | None = None


class FreeAuditClaimResponse(BaseModel):
    site_id: uuid.UUID
    domain: str
    crawl_job_id: uuid.UUID
    crawl_status: str
    reused_site: bool
    reused_crawl: bool
    claimed_at: datetime
