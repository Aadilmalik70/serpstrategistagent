import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GoogleDataConnectionResponse(BaseModel):
    status: str
    google_email: str | None
    scopes: list[str]
    gsc_property: str | None
    ga4_property_id: str | None
    ga4_property_name: str | None
    baseline_status: str
    baseline_summary: dict[str, Any]
    last_synced_at: datetime | None
    connected_at: datetime | None
    last_refreshed_at: datetime | None
    last_error: str | None


class GoogleOAuthStartResponse(BaseModel):
    authorization_url: str


class GooglePropertyOption(BaseModel):
    id: str
    name: str
    type: str
    permission_level: str | None = None


class GooglePropertyCatalogResponse(BaseModel):
    gsc_properties: list[GooglePropertyOption]
    ga4_properties: list[GooglePropertyOption]


class GooglePropertySelectionRequest(BaseModel):
    gsc_property: str | None = Field(default=None, max_length=2048)
    ga4_property_id: str | None = Field(default=None, max_length=128)
    ga4_property_name: str | None = Field(default=None, max_length=255)


class SearchSyncJobResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    status: Literal["queued", "running", "retry_wait", "completed", "failed", "cancelled"]
    attempt_count: int
    max_attempts: int
    reused: bool = False
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    run_after: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancellation_requested: bool
    created_at: datetime
    completed_at: datetime | None = None


class SearchOpportunityResponse(BaseModel):
    id: str
    site_id: str
    opportunity_type: str
    status: str
    title: str
    query: str | None
    page_url: str | None
    priority_score: int
    confidence_score: int
    metrics: dict[str, Any]
    evidence: list[Any]
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None


class SearchOpportunityListResponse(BaseModel):
    items: list[SearchOpportunityResponse]
    total: int
