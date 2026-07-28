from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.content_intelligence import ContentIntelligenceResponse, InternalLinkRecommendationResponse
from app.services.content_intelligence_service import analyze_site_content

router = APIRouter(prefix="/sites", tags=["content-intelligence"])


@router.get("/{site_id}/content-intelligence", response_model=ContentIntelligenceResponse)
async def get_content_intelligence(
    site_id: uuid.UUID,
    refresh: bool = Query(default=False),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContentIntelligenceResponse:
    try:
        result = await analyze_site_content(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
            create_actions=False if not refresh else True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContentIntelligenceResponse.model_validate(result)


@router.post("/{site_id}/content-intelligence/analyze", response_model=ContentIntelligenceResponse)
async def analyze_content_intelligence(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContentIntelligenceResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        result = await analyze_site_content(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
            create_actions=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContentIntelligenceResponse.model_validate(result)


@router.get("/{site_id}/semantic-graph", response_model=ContentIntelligenceResponse)
async def get_semantic_graph(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ContentIntelligenceResponse:
    try:
        result = await analyze_site_content(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
            create_actions=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContentIntelligenceResponse.model_validate(result)


@router.get("/{site_id}/internal-link-recommendations", response_model=list[InternalLinkRecommendationResponse])
async def get_internal_link_recommendations(
    site_id: uuid.UUID,
    include_resolved: bool = Query(default=False),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[InternalLinkRecommendationResponse]:
    try:
        result = await analyze_site_content(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
            create_actions=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = result["recommendations"]
    if not include_resolved:
        items = [item for item in items if item["status"] == "active"]
    return [InternalLinkRecommendationResponse.model_validate(item) for item in items]
