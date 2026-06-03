import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.page import Page
from app.schemas.site import SiteCreate, SiteResponse, SiteDetailResponse
from app.services.site_service import (
    create_site,
    get_sites,
    get_site_by_id,
    get_site_by_domain,
    get_site_page_count,
    delete_site,
)

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
    return SiteDetailResponse(
        id=site.id,
        domain=site.domain,
        name=site.name,
        status=site.status,
        created_at=site.created_at,
        updated_at=site.updated_at,
        page_count=page_count,
        tech_stack=site.tech_stack,
        cms=site.cms,
        github_connected=bool(site.github_repo and site.github_token),
        wordpress_connected=bool(site.wordpress_url and site.wordpress_user and site.wordpress_app_password),
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
