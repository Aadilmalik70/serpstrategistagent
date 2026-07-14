import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.agent_run import AgentRun
from app.models.issue import Issue
from app.models.page import Page
from app.models.site import Site
from app.schemas.site import LatestRunInfo, SiteCreate, SiteDetailResponse, SiteResponse
from app.services.health_score import calculate_health_score
from app.services.site_service import (
    create_site,
    delete_site,
    get_site_by_domain,
    get_site_by_id,
    get_site_page_count,
    get_sites,
)

router = APIRouter(prefix="/sites", tags=["sites"])


async def _require_site(
    db: AsyncSession,
    context: WorkspaceContext,
    site_id: uuid.UUID,
) -> Site:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        # Do not reveal whether a site exists in another workspace.
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.post("", status_code=201, response_model=SiteResponse)
async def create_site_endpoint(
    data: SiteCreate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    existing = await get_site_by_domain(db, data.domain)
    if existing:
        raise HTTPException(status_code=409, detail="Site with this domain already exists")
    return await create_site(db, data, context.workspace.id)


@router.get("", response_model=list[SiteResponse])
async def list_sites_endpoint(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return await get_sites(db, context.workspace.id)


@router.get("/{site_id}", response_model=SiteDetailResponse)
async def get_site_endpoint(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    site = await _require_site(db, context, site_id)
    page_count = await get_site_page_count(db, site_id)
    issue_count_result = await db.execute(
        select(func.count(Issue.id)).where(Issue.site_id == site_id, Issue.status.in_(["open", "regressed"]))
    )
    issue_count = issue_count_result.scalar() or 0

    latest_run_result = await db.execute(
        select(AgentRun)
        .where(AgentRun.site_id == site_id, AgentRun.status == "completed")
        .order_by(AgentRun.completed_at.desc())
        .limit(1)
    )
    latest_run_obj = latest_run_result.scalar_one_or_none()

    latest_run = None
    health_score = None
    health_grade = None
    if latest_run_obj:
        latest_run = LatestRunInfo(
            id=latest_run_obj.id,
            status=latest_run_obj.status,
            pages_analyzed=latest_run_obj.pages_analyzed or 0,
            issues_found=latest_run_obj.issues_found or 0,
            summary=latest_run_obj.summary,
            completed_at=latest_run_obj.completed_at,
        )
        health = await calculate_health_score(db, site_id)
        health_score = health.get("score")
        health_grade = health.get("grade")

    settings = get_settings()
    return SiteDetailResponse(
        id=site.id,
        domain=site.domain,
        name=site.name,
        status=site.status,
        created_at=site.created_at,
        updated_at=site.updated_at,
        page_count=page_count,
        issue_count=issue_count,
        tech_stack=site.tech_stack,
        cms=site.cms,
        github_connected=bool(site.github_repo and site.github_token),
        wordpress_connected=bool(site.wordpress_url and site.wordpress_user and site.wordpress_app_password),
        health_score=health_score,
        health_grade=health_grade,
        latest_run=latest_run,
        librecrawl_enabled=settings.librecrawl_enabled,
    )


@router.delete("/{site_id}", status_code=204)
async def delete_site_endpoint(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    deleted = await delete_site(db, site_id, context.workspace.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Site not found")


@router.get("/{site_id}/pages")
async def list_site_pages(
    site_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("path"),
    order: str = Query("asc"),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    allowed_sort_cols = {"path", "title", "status_code", "word_count", "response_time_ms"}
    sort_col = getattr(Page, sort) if sort in allowed_sort_cols else Page.path
    order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

    offset = (page - 1) * limit
    query = select(Page).where(Page.site_id == site_id).order_by(order_clause).offset(offset).limit(limit)
    pages = list((await db.execute(query)).scalars().all())
    total = (await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))).scalar_one()

    return {
        "items": pages,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/{site_id}/status-codes")
async def get_status_codes(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    result = await db.execute(
        select(Page.status_code, func.count(Page.id))
        .where(Page.site_id == site_id, Page.status_code.isnot(None))
        .group_by(Page.status_code)
        .order_by(Page.status_code)
    )
    rows = result.all()
    total = sum(row[1] for row in rows)
    return [
        {
            "status_code": row[0],
            "count": row[1],
            "percentage": round(row[1] / total * 100, 1) if total else 0,
        }
        for row in rows
    ]


@router.get("/{site_id}/eeat")
async def get_eeat_score(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    pages = list((await db.execute(select(Page).where(Page.site_id == site_id))).scalars().all())
    if not pages:
        return {"score": 0, "total_pages": 0, "signals": {}}

    total = len(pages)
    has_schema = 0
    has_og = 0
    has_external_links = 0
    has_author = 0
    has_https = 0
    has_sufficient_content = 0
    total_external_citations = 0

    for page_row in pages:
        meta = page_row.meta or {}
        json_ld = meta.get("json_ld")
        if json_ld:
            has_schema += 1
            if isinstance(json_ld, list):
                for item in json_ld:
                    if isinstance(item, dict) and item.get("author"):
                        has_author += 1
                        break
            elif isinstance(json_ld, dict) and json_ld.get("author"):
                has_author += 1
        if meta.get("og_tags"):
            has_og += 1
        external_count = meta.get("external_links_count", 0)
        if external_count and external_count > 0:
            has_external_links += 1
            total_external_citations += external_count
        has_https += 1
        if page_row.word_count and page_row.word_count >= 300:
            has_sufficient_content += 1

    signals = {
        "author_attribution": {"count": has_author, "total": total, "pct": round(has_author / total * 100)},
        "structured_data": {"count": has_schema, "total": total, "pct": round(has_schema / total * 100)},
        "external_links": {"count": has_external_links, "total": total, "pct": round(has_external_links / total * 100)},
        "og_tags": {"count": has_og, "total": total, "pct": round(has_og / total * 100)},
        "https_secure": {"count": has_https, "total": total, "pct": round(has_https / total * 100)},
        "sufficient_content": {"count": has_sufficient_content, "total": total, "pct": round(has_sufficient_content / total * 100)},
    }
    weights = {
        "author_attribution": 0.20,
        "structured_data": 0.20,
        "external_links": 0.15,
        "og_tags": 0.15,
        "https_secure": 0.15,
        "sufficient_content": 0.15,
    }
    score = sum(signals[key]["pct"] * weights[key] for key in weights)
    return {
        "score": round(score),
        "total_pages": total,
        "signals": signals,
        "external_citations_total": total_external_citations,
        "avg_citations_per_page": round(total_external_citations / total, 1) if total else 0,
    }


@router.get("/{site_id}/links")
async def get_internal_links(
    site_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    offset = (page - 1) * limit
    rows = (
        await db.execute(
            select(Page.id, Page.path, Page.title, Page.meta)
            .where(Page.site_id == site_id)
            .order_by(Page.path)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    items = []
    for row in rows:
        meta = row[3] or {}
        items.append(
            {
                "id": str(row[0]),
                "path": row[1],
                "title": row[2],
                "internal_links_count": meta.get("internal_links_count", 0),
                "external_links_count": meta.get("external_links_count", 0),
                "linked_from": meta.get("linked_from", []),
                "inlinks_count": len(meta.get("linked_from", [])),
            }
        )

    total = (await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))).scalar_one()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/{site_id}/export")
async def export_site_data(
    site_id: uuid.UUID,
    format: str = Query("csv"),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    site = await _require_site(db, context, site_id)
    pages = list(
        (await db.execute(select(Page).where(Page.site_id == site_id).order_by(Page.path))).scalars().all()
    )

    if format == "json":
        return [
            {
                "url": f"https://{site.domain}{page_row.path}",
                "path": page_row.path,
                "status_code": page_row.status_code,
                "title": page_row.title,
                "meta_description": page_row.meta_description,
                "h1": page_row.h1,
                "word_count": page_row.word_count,
                "response_time_ms": page_row.response_time_ms,
                "canonical_url": page_row.canonical_url,
                "internal_links": (page_row.meta or {}).get("internal_links_count", 0),
                "external_links": (page_row.meta or {}).get("external_links_count", 0),
                "images_count": (page_row.meta or {}).get("images_count", 0),
            }
            for page_row in pages
        ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "URL",
            "Status",
            "Title",
            "Meta Description",
            "H1",
            "Words",
            "Response (ms)",
            "Canonical",
            "Internal Links",
            "External Links",
            "Images",
        ]
    )
    for page_row in pages:
        meta = page_row.meta or {}
        writer.writerow(
            [
                f"https://{site.domain}{page_row.path}",
                page_row.status_code,
                page_row.title or "",
                page_row.meta_description or "",
                page_row.h1 or "",
                page_row.word_count or "",
                page_row.response_time_ms or "",
                page_row.canonical_url or "",
                meta.get("internal_links_count", 0),
                meta.get("external_links_count", 0),
                meta.get("images_count", 0),
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={site.domain}-crawl-export.csv"},
    )


@router.get("/{site_id}/visualization")
async def get_visualization_data(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    rows = (
        await db.execute(
            select(Page.id, Page.path, Page.title, Page.status_code, Page.meta).where(Page.site_id == site_id)
        )
    ).all()

    path_to_id: dict[str, str] = {}
    nodes = []
    for row in rows:
        path_to_id[row[1]] = str(row[0])
        meta = row[4] or {}
        nodes.append(
            {
                "id": str(row[0]),
                "path": row[1],
                "title": row[2] or row[1],
                "status_code": row[3],
                "internal_links_count": meta.get("internal_links_count", 0),
                "inlinks_count": len(meta.get("linked_from", [])),
            }
        )

    edges = []
    for row in rows:
        from urllib.parse import urlparse

        target_id = str(row[0])
        for source_url in (row[4] or {}).get("linked_from", []):
            source_path = urlparse(source_url).path or "/"
            source_id = path_to_id.get(source_path)
            if source_id and source_id != target_id:
                edges.append({"source": source_id, "target": target_id})

    return {"nodes": nodes, "edges": edges}
