import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator
from urllib.parse import urlparse


class SiteCreate(BaseModel):
    domain: str
    name: str | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        # Add scheme if missing for proper parsing
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        parsed = urlparse(v)
        if not parsed.netloc or "." not in parsed.netloc:
            raise ValueError("Invalid domain format")
        # Return just the netloc (domain without scheme)
        return parsed.netloc


class SiteResponse(BaseModel):
    id: uuid.UUID
    domain: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SiteDetailResponse(SiteResponse):
    page_count: int = 0
    last_crawled_at: datetime | None = None
    tech_stack: str | None = None
    cms: str | None = None
    github_connected: bool = False
    wordpress_connected: bool = False
