from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field


FindingStatus = Literal["open", "regressed", "resolved", "dismissed"]


class TechnicalFindingResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    page_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    source_crawl_id: uuid.UUID | None
    finding_type: str
    fingerprint: str
    detector_version: str
    category: str
    severity: str
    status: str
    title: str
    description: str
    recommendation: str | None
    affected_url: str | None
    affected_urls: list[str]
    evidence: list[dict[str, Any]]
    impact_score: int
    confidence_score: int
    effort_score: int
    occurrence_count: int
    regression_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    action_id: uuid.UUID | None = None
    action_status: str | None = None


class TechnicalFindingQueueResponse(BaseModel):
    items: list[TechnicalFindingResponse]
    total: int
    counts_by_status: dict[str, int]
    counts_by_severity: dict[str, int]


class FindingStatusUpdate(BaseModel):
    status: Literal["open", "dismissed"]


class FindingRefreshResponse(BaseModel):
    created: int = 0
    updated: int = 0
    regressed: int = 0
    resolved: int = 0
    active: int = 0
    actions_created: int = 0
    action_ids: list[uuid.UUID] = Field(default_factory=list)
