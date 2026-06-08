import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.page import Page
from app.models.agent_run import AgentRun
from app.models.issue import Issue
from app.schemas.site import SiteCreate, SiteResponse, SiteDetailResponse, LatestRunInfo
from app.services.site_service import (
    create_site,
    get_sites,
    get_site_by_id,
    get_site_by_domain,
    get_site_page_count,
    delete_site,
)
from app.services.health_score import calculate_health_score
from app.config import get_settings

router = APIRouter(prefix="/sites", tags=["sites"])


@router.post("", status_code=201, response_model=SiteResponse)
async def create_site_endpoint(data: SiteCreate, db: AsyncSession = Depends(get_db)):
    existing = await get_site_by_domain(db, data.domain)
    if existing:
        raise HTTPException(status_code=409, detail="Site with this domain already exists")
    site = await create_site(db, data)
    return site


@router.get("", response_model=list[SiteResponse])
async def list_sites_endpoint(db: AsyncSession = Depends(get_db)):
    return await get_sites(db)


@router.get("/{site_id}", response_model=SiteDetailResponse)
async def get_site_endpoint(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    site = await get_site_by_id(db, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    page_count = await get_site_page_count(db, site_id)
    issue_count_result = await db.execute(
        select(func.count(Issue.id)).where(Issue.site_id == site_id, Issue.status == "open")
    )
    issue_count = issue_count_result.scalar() or 0

    # Get latest completed agent run
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
        # Calculate health score
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
async def delete_site_endpoint(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await delete_site(db, site_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Site not found")


@router.get("/{site_id}/pages")
async def list_site_pages(
    site_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("path"),
    order: str = Query("asc"),
    db: AsyncSession = Depends(get_db),
):
    site = await get_site_by_id(db, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Build query
    allowed_sort_cols = {"path", "title", "status_code", "word_count", "response_time_ms"}
    sort_col = getattr(Page, sort) if sort in allowed_sort_cols else Page.path
    order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

    offset = (page - 1) * limit
    query = select(Page).where(Page.site_id == site_id).order_by(order_clause).offset(offset).limit(limit)
    result = await db.execute(query)
    pages = list(result.scalars().all())

    # Total count
    count_result = await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))
    total = count_result.scalar_one()

    return {
        "items": pages,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/{site_id}/status-codes")
async def get_status_codes(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Status code distribution across all pages."""
    result = await db.execute(
        select(Page.status_code, func.count(Page.id))
        .where(Page.site_id == site_id, Page.status_code.isnot(None))
        .group_by(Page.status_code)
        .order_by(Page.status_code)
    )
    rows = result.all()
    total = sum(r[1] for r in rows)
    return [
        {
            "status_code": r[0],
            "count": r[1],
            "percentage": round(r[1] / total * 100, 1) if total else 0,
        }
        for r in rows
    ]


@router.get("/{site_id}/eeat")
async def get_eeat_score(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Compute E-E-A-T score from stored page meta data."""
    result = await db.execute(
        select(Page).where(Page.site_id == site_id)
    )
    pages = list(result.scalars().all())
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

    for p in pages:
        meta = p.meta or {}
        # Schema/JSON-LD
        json_ld = meta.get("json_ld")
        if json_ld:
            has_schema += 1
            # Check for author in Article schemas
            if isinstance(json_ld, list):
                for item in json_ld:
                    if isinstance(item, dict) and item.get("author"):
                        has_author += 1
                        break
            elif isinstance(json_ld, dict) and json_ld.get("author"):
                has_author += 1
        # OG tags
        if meta.get("og_tags"):
            has_og += 1
        # External links
        ext_count = meta.get("external_links_count", 0)
        if ext_count and ext_count > 0:
            has_external_links += 1
            total_external_citations += ext_count
        # HTTPS (all pages from LibreCrawl are https)
        has_https += 1
        # Sufficient content (>= 300 words)
        if p.word_count and p.word_count >= 300:
            has_sufficient_content += 1

    # Calculate score (weighted)
    signals = {
        "author_attribution": {"count": has_author, "total": total, "pct": round(has_author / total * 100)},
        "structured_data": {"count": has_schema, "total": total, "pct": round(has_schema / total * 100)},
        "external_links": {"count": has_external_links, "total": total, "pct": round(has_external_links / total * 100)},
        "og_tags": {"count": has_og, "total": total, "pct": round(has_og / total * 100)},
        "https_secure": {"count": has_https, "total": total, "pct": round(has_https / total * 100)},
        "sufficient_content": {"count": has_sufficient_content, "total": total, "pct": round(has_sufficient_content / total * 100)},
    }

    # Weighted score: author 20%, schema 20%, external 15%, OG 15%, HTTPS 15%, content 15%
    weights = {"author_attribution": 0.20, "structured_data": 0.20, "external_links": 0.15,
               "og_tags": 0.15, "https_secure": 0.15, "sufficient_content": 0.15}
    score = sum(signals[k]["pct"] * weights[k] for k in weights)

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
    db: AsyncSession = Depends(get_db),
):
    """Internal link map — pages with their link counts and linked_from data."""
    offset = (page - 1) * limit
    result = await db.execute(
        select(Page.id, Page.path, Page.title, Page.meta)
        .where(Page.site_id == site_id)
        .order_by(Page.path)
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    items = []
    for r in rows:
        meta = r[3] or {}
        items.append({
            "id": str(r[0]),
            "path": r[1],
            "title": r[2],
            "internal_links_count": meta.get("internal_links_count", 0),
            "external_links_count": meta.get("external_links_count", 0),
            "linked_from": meta.get("linked_from", []),
            "inlinks_count": len(meta.get("linked_from", [])),
        })

    count_result = await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))
    total = count_result.scalar_one()

    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/{site_id}/export")
async def export_site_data(
    site_id: uuid.UUID,
    format: str = Query("csv"),
    db: AsyncSession = Depends(get_db),
):
    """Export all page data as CSV or JSON."""
    site = await get_site_by_id(db, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(select(Page).where(Page.site_id == site_id).order_by(Page.path))
    pages = list(result.scalars().all())

    if format == "json":
        data = []
        for p in pages:
            meta = p.meta or {}
            data.append({
                "url": f"https://{site.domain}{p.path}",
                "path": p.path,
                "status_code": p.status_code,
                "title": p.title,
                "meta_description": p.meta_description,
                "h1": p.h1,
                "word_count": p.word_count,
                "response_time_ms": p.response_time_ms,
                "canonical_url": p.canonical_url,
                "internal_links": meta.get("internal_links_count", 0),
                "external_links": meta.get("external_links_count", 0),
                "images_count": meta.get("images_count", 0),
            })
        return data

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Status", "Title", "Meta Description", "H1", "Words",
                     "Response (ms)", "Canonical", "Internal Links", "External Links", "Images"])
    for p in pages:
        meta = p.meta or {}
        writer.writerow([
            f"https://{site.domain}{p.path}",
            p.status_code,
            p.title or "",
            p.meta_description or "",
            p.h1 or "",
            p.word_count or "",
            p.response_time_ms or "",
            p.canonical_url or "",
            meta.get("internal_links_count", 0),
            meta.get("external_links_count", 0),
            meta.get("images_count", 0),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={site.domain}-crawl-export.csv"},
    )


@router.get("/{site_id}/visualization")
async def get_visualization_data(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Site link graph data for visualization — nodes and edges."""
    result = await db.execute(
        select(Page.id, Page.path, Page.title, Page.status_code, Page.meta)
        .where(Page.site_id == site_id)
    )
    rows = result.all()

    # Build path->id lookup
    path_to_id = {}
    nodes = []
    for r in rows:
        path_to_id[r[1]] = str(r[0])
        meta = r[4] or {}
        nodes.append({
            "id": str(r[0]),
            "path": r[1],
            "title": r[2] or r[1],
            "status_code": r[3],
            "internal_links_count": meta.get("internal_links_count", 0),
            "inlinks_count": len(meta.get("linked_from", [])),
        })

    # Build edges from linked_from data
    edges = []
    for r in rows:
        meta = r[4] or {}
        linked_from = meta.get("linked_from", [])
        target_id = str(r[0])
        for source_url in linked_from:
            # Extract path from full URL
            from urllib.parse import urlparse
            source_path = urlparse(source_url).path or "/"
            source_id = path_to_id.get(source_path)
            if source_id and source_id != target_id:
                edges.append({"source": source_id, "target": target_id})

    return {"nodes": nodes, "edges": edges}
