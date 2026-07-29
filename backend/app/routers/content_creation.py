from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.content_creation import ContentBrief, ContentDraft
from app.schemas.content_creation import (
    ContentBriefCreate,
    ContentBriefResponse,
    ContentDraftResponse,
    ContentDraftUpdate,
    ContentOpportunityResponse,
    ContentWorkspaceResponse,
    DraftGenerateRequest,
    QualityCheckResponse,
)
from app.services.content_creation_service import (
    ContentCreationError,
    create_brief,
    generate_draft,
    get_workspace,
    list_briefs,
    list_drafts,
    quality_to_dict,
    run_quality_check,
    submit_for_approval,
    update_draft,
)

router = APIRouter(tags=["serp-content"])


def _error(exc: ContentCreationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/sites/{site_id}/content", response_model=ContentWorkspaceResponse)
async def content_workspace(site_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    try:
        return ContentWorkspaceResponse.model_validate(await get_workspace(db, workspace_id=context.workspace.id, site_id=site_id))
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.get("/sites/{site_id}/content/opportunities", response_model=list[ContentOpportunityResponse])
async def content_opportunities(site_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    try:
        workspace = await get_workspace(db, workspace_id=context.workspace.id, site_id=site_id)
        return [ContentOpportunityResponse.model_validate(item) for item in workspace["opportunities"]]
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.get("/sites/{site_id}/content/briefs", response_model=list[ContentBriefResponse])
async def content_briefs(site_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    try:
        return [ContentBriefResponse.model_validate(item) for item in await list_briefs(db, workspace_id=context.workspace.id, site_id=site_id)]
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.get("/sites/{site_id}/content/drafts", response_model=list[ContentDraftResponse])
async def content_drafts(site_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    try:
        return [ContentDraftResponse.model_validate(item) for item in await list_drafts(db, workspace_id=context.workspace.id, site_id=site_id)]
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.post("/sites/{site_id}/content/briefs", response_model=ContentBriefResponse)
async def create_content_brief(site_id: uuid.UUID, data: ContentBriefCreate, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    require_workspace_role(context, "owner", "admin", "editor")
    try:
        item = await create_brief(db, workspace_id=context.workspace.id, site_id=site_id, data=data)
        return ContentBriefResponse.model_validate({"id": item.id, "site_id": item.site_id, "opportunity_id": item.opportunity_id, "page_id": item.page_id, "status": item.status, "title": item.title, "target_query": item.target_query, "search_intent": item.search_intent, "page_type": item.page_type, "audience": item.audience, "business_goal": item.business_goal, "outline": item.outline or [], "required_topics": item.required_topics or [], "required_entities": item.required_entities or [], "internal_link_targets": item.internal_link_targets or [], "faq_questions": item.faq_questions or [], "schema_recommendations": item.schema_recommendations or [], "information_gain": item.information_gain or [], "evidence": item.evidence or [], "scores": item.scores or {}, "created_at": item.created_at, "updated_at": item.updated_at})
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.post("/content/briefs/{brief_id}/generate", response_model=ContentDraftResponse)
async def generate_content_draft(brief_id: uuid.UUID, data: DraftGenerateRequest, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    require_workspace_role(context, "owner", "admin", "editor")
    try:
        item = await db.scalar(select(ContentBrief).where(ContentBrief.id == brief_id))
        if not item or item.workspace_id != context.workspace.id:
            raise ContentCreationError("Content brief not found", 404)
        draft = await generate_draft(db, workspace_id=context.workspace.id, site_id=item.site_id, brief_id=brief_id, mode=data.mode)
        return ContentDraftResponse.model_validate({"id": draft.id, "site_id": draft.site_id, "brief_id": draft.brief_id, "action_id": draft.action_id, "status": draft.status, "title": draft.title, "slug": draft.slug, "meta_title": draft.meta_title, "meta_description": draft.meta_description, "body_markdown": draft.body_markdown, "generation_mode": draft.generation_mode, "word_count": draft.word_count, "version": draft.version, "quality_summary": draft.quality_summary or {}, "created_at": draft.created_at, "updated_at": draft.updated_at})
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.post("/content/drafts/{draft_id}/quality-check", response_model=QualityCheckResponse)
async def quality_check(draft_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    require_workspace_role(context, "owner", "admin", "editor")
    try:
        draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.workspace_id == context.workspace.id))
        if not draft:
            raise ContentCreationError("Content draft not found", 404)
        result = await run_quality_check(db, workspace_id=context.workspace.id, site_id=draft.site_id, draft_id=draft_id)
        return QualityCheckResponse.model_validate(quality_to_dict(result))
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.put("/content/drafts/{draft_id}", response_model=ContentDraftResponse)
async def edit_content_draft(draft_id: uuid.UUID, data: ContentDraftUpdate, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    require_workspace_role(context, "owner", "admin", "editor")
    try:
        draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.workspace_id == context.workspace.id))
        if not draft:
            raise ContentCreationError("Content draft not found", 404)
        item = await update_draft(db, workspace_id=context.workspace.id, site_id=draft.site_id, draft_id=draft_id, data=data)
        return ContentDraftResponse.model_validate({"id": item.id, "site_id": item.site_id, "brief_id": item.brief_id, "action_id": item.action_id, "status": item.status, "title": item.title, "slug": item.slug, "meta_title": item.meta_title, "meta_description": item.meta_description, "body_markdown": item.body_markdown, "generation_mode": item.generation_mode, "word_count": item.word_count, "version": item.version, "quality_summary": item.quality_summary or {}, "created_at": item.created_at, "updated_at": item.updated_at})
    except ContentCreationError as exc:
        raise _error(exc) from exc


@router.post("/content/drafts/{draft_id}/submit-for-approval", response_model=ContentDraftResponse)
async def submit_draft(draft_id: uuid.UUID, context: WorkspaceContext = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    require_workspace_role(context, "owner", "admin", "editor")
    try:
        draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.workspace_id == context.workspace.id))
        if not draft:
            raise ContentCreationError("Content draft not found", 404)
        item = await submit_for_approval(db, workspace_id=context.workspace.id, user_id=context.user.id, site_id=draft.site_id, draft_id=draft_id)
        return ContentDraftResponse.model_validate({"id": item.id, "site_id": item.site_id, "brief_id": item.brief_id, "action_id": item.action_id, "status": item.status, "title": item.title, "slug": item.slug, "meta_title": item.meta_title, "meta_description": item.meta_description, "body_markdown": item.body_markdown, "generation_mode": item.generation_mode, "word_count": item.word_count, "version": item.version, "quality_summary": item.quality_summary or {}, "created_at": item.created_at, "updated_at": item.updated_at})
    except ContentCreationError as exc:
        raise _error(exc) from exc
