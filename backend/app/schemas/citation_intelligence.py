from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, Field, field_validator


class CitationPromptSetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    brand_terms: list[str] = Field(min_length=1, max_length=20)
    competitor_terms: list[str] = Field(default_factory=list, max_length=20)
    prompts: list[str] = Field(min_length=1, max_length=50)
    providers: list[str] = Field(default_factory=lambda: ["manual"], max_length=10)
    schedule_interval_hours: int | None = Field(default=None, ge=1, le=720)

    @field_validator("name", "brand_terms", "competitor_terms", "prompts", "providers")
    @classmethod
    def strip_values(cls, value):
        if isinstance(value, str):
            return value.strip()
        return [item.strip() for item in value if item.strip()]


class CitationPromptSetResponse(CitationPromptSetCreate):
    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CitationScanCreate(BaseModel):
    prompt_set_id: uuid.UUID


class CitationResultIngest(BaseModel):
    provider: str = Field(min_length=2, max_length=64)
    prompt: str = Field(min_length=2, max_length=5000)
    answer: str = Field(default="", max_length=50_000)
    cited_urls: list[str] = Field(default_factory=list, max_length=100)


class CitationResultResponse(BaseModel):
    id: uuid.UUID
    provider: str
    prompt: str
    answer_excerpt: str
    brand_mentioned: bool
    cited_urls: list[str]
    competitor_mentions: list[str]
    evidence: list[dict[str, Any]]
    captured_at: datetime


class CitationGapResponse(BaseModel):
    id: uuid.UUID
    gap_type: str
    status: str
    prompt: str
    competitor: str | None
    priority_score: int
    confidence_score: int
    evidence: list[dict[str, Any]]
    action_id: uuid.UUID | None
    last_detected_at: datetime


class CitationScanResponse(BaseModel):
    id: uuid.UUID
    prompt_set_id: uuid.UUID
    status: str
    providers: list[str]
    prompt_count: int
    result_count: int
    visibility_score: int
    mention_rate: float
    citation_rate: float
    competitor_metrics: dict[str, Any]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class CitationIntelligenceResponse(BaseModel):
    prompt_sets: list[CitationPromptSetResponse]
    latest_scan: CitationScanResponse | None
    results: list[CitationResultResponse]
    gaps: list[CitationGapResponse]
    provider_notes: list[str]
