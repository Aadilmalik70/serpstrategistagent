from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, field_validator


class ContentBriefCreate(BaseModel):
    opportunity_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    topic: str | None = Field(default=None, min_length=2, max_length=500)
    target_query: str | None = Field(default=None, max_length=500)
    page_type: str = Field(default="guide", min_length=2, max_length=64)
    audience: str = Field(default="", max_length=500)
    business_goal: str = Field(default="", max_length=500)

    @field_validator("topic", "target_query", "page_type", "audience", "business_goal")
    @classmethod
    def strip_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class ContentOpportunityResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    page_id: uuid.UUID | None
    opportunity_type: str
    status: str
    title: str
    summary: str
    target_query: str | None
    target_path: str | None
    priority_score: int
    confidence_score: int
    effort_score: int
    evidence: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ContentBriefResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    page_id: uuid.UUID | None
    status: str
    title: str
    target_query: str | None
    search_intent: str
    page_type: str
    audience: str
    business_goal: str
    outline: list[dict[str, Any]]
    required_topics: list[str]
    required_entities: list[str]
    internal_link_targets: list[dict[str, Any]]
    faq_questions: list[str]
    schema_recommendations: list[str]
    information_gain: list[str]
    evidence: list[dict[str, Any]]
    scores: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DraftGenerateRequest(BaseModel):
    mode: Literal["evidence_scaffold", "ai_assisted"] = "evidence_scaffold"


class ContentDraftUpdate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    meta_title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=1024)
    body_markdown: str = Field(default="", max_length=250_000)


class ContentDraftResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    brief_id: uuid.UUID
    action_id: uuid.UUID | None
    status: str
    title: str
    slug: str
    meta_title: str
    meta_description: str
    body_markdown: str
    generation_mode: str
    word_count: int
    version: int
    quality_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class QualityCheckResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    overall_score: int
    passed: bool
    checks: list[dict[str, Any]]
    created_at: datetime


class ContentWorkspaceResponse(BaseModel):
    opportunities: list[ContentOpportunityResponse]
    briefs: list[ContentBriefResponse]
    drafts: list[ContentDraftResponse]
    counts: dict[str, int]
