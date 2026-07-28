from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.citation_intelligence import (
    CitationIntelligenceResponse,
    CitationPromptSetCreate,
    CitationPromptSetResponse,
    CitationResultIngest,
    CitationResultResponse,
    CitationScanCreate,
    CitationScanResponse,
)
from app.services.citation_intelligence_service import (
    create_prompt_set,
    create_scan,
    finalize_scan,
    get_dashboard,
    ingest_result,
    list_prompt_sets,
    prompt_set_to_dict,
    result_to_dict,
    scan_to_dict,
)

router = APIRouter(prefix="/sites", tags=["citation-intelligence"])


@router.get("/{site_id}/citation-intelligence", response_model=CitationIntelligenceResponse)
async def citation_dashboard(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CitationIntelligenceResponse:
    try:
        return CitationIntelligenceResponse.model_validate(await get_dashboard(db, workspace_id=context.workspace.id, site_id=site_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{site_id}/citation-intelligence/prompt-sets", response_model=CitationPromptSetResponse)
async def create_citation_prompt_set(
    site_id: uuid.UUID,
    data: CitationPromptSetCreate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CitationPromptSetResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        item = await create_prompt_set(db, workspace_id=context.workspace.id, site_id=site_id, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CitationPromptSetResponse.model_validate(prompt_set_to_dict(item))


@router.get("/{site_id}/citation-intelligence/prompt-sets", response_model=list[CitationPromptSetResponse])
async def get_citation_prompt_sets(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[CitationPromptSetResponse]:
    try:
        items = await list_prompt_sets(db, workspace_id=context.workspace.id, site_id=site_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [CitationPromptSetResponse.model_validate(prompt_set_to_dict(item)) for item in items]


@router.post("/{site_id}/citation-intelligence/scans", response_model=CitationScanResponse)
async def start_citation_scan(
    site_id: uuid.UUID,
    data: CitationScanCreate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CitationScanResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        item = await create_scan(db, workspace_id=context.workspace.id, site_id=site_id, prompt_set_id=data.prompt_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CitationScanResponse.model_validate(scan_to_dict(item))


@router.post("/{site_id}/citation-intelligence/scans/{scan_id}/results", response_model=CitationResultResponse)
async def ingest_citation_result(
    site_id: uuid.UUID,
    scan_id: uuid.UUID,
    data: CitationResultIngest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CitationResultResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        item = await ingest_result(db, workspace_id=context.workspace.id, site_id=site_id, scan_id=scan_id, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CitationResultResponse.model_validate(result_to_dict(item))


@router.post("/{site_id}/citation-intelligence/scans/{scan_id}/finalize", response_model=CitationScanResponse)
async def finalize_citation_scan(
    site_id: uuid.UUID,
    scan_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CitationScanResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        item = await finalize_scan(db, workspace_id=context.workspace.id, site_id=site_id, scan_id=scan_id, create_actions=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CitationScanResponse.model_validate(scan_to_dict(item))
