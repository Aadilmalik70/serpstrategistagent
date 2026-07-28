from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel


class ContentInsightResponse(BaseModel):
    id: uuid.UUID
    page_id: uuid.UUID
    path: str
    title: str | None
    content_age_days: int
    freshness_score: int
    decay_score: int
    information_gain_score: int
    topics: list[str]
    entities: list[str]
    unique_terms: list[str]
    metrics: dict[str, Any]
    evidence: list[Any]
    analyzed_at: datetime


class InternalLinkRecommendationResponse(BaseModel):
    id: uuid.UUID
    source_page_id: uuid.UUID
    source_path: str
    target_page_id: uuid.UUID
    target_path: str
    target_title: str | None
    anchor_text: str
    priority_score: int
    confidence_score: int
    reason: str
    evidence: list[Any]
    status: str
    last_detected_at: datetime


class SemanticGraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    topic_clusters: list[dict[str, Any]]


class ContentIntelligenceResponse(BaseModel):
    analyzed_at: datetime
    period_end: str
    total_pages: int
    decaying_pages: int
    orphan_pages: int
    insights: list[ContentInsightResponse]
    recommendations: list[InternalLinkRecommendationResponse]
    semantic_graph: SemanticGraphResponse
    action_ids: list[uuid.UUID] = []
