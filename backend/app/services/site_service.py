import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page import Page
from app.models.site import Site
from app.schemas.site import SiteCreate
from app.services.entitlement_service import assert_resource_quota


async def create_site(db: AsyncSession, data: SiteCreate, workspace_id: uuid.UUID) -> Site:
    current_sites = int(
        await db.scalar(select(func.count(Site.id)).where(Site.workspace_id == workspace_id)) or 0
    )
    await assert_resource_quota(
        db,
        workspace_id=workspace_id,
        metric="sites",
        current=current_sites,
    )

    name = data.name or data.domain
    site = Site(domain=data.domain, name=name, workspace_id=workspace_id)
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


async def get_sites(db: AsyncSession, workspace_id: uuid.UUID) -> list[Site]:
    result = await db.execute(
        select(Site)
        .where(Site.workspace_id == workspace_id)
        .order_by(Site.created_at.desc())
    )
    return list(result.scalars().all())


async def get_site_by_id(
    db: AsyncSession,
    site_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Site | None:
    result = await db.execute(
        select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def get_site_by_domain(db: AsyncSession, domain: str) -> Site | None:
    """Domains remain globally unique while ownership verification is introduced."""
    result = await db.execute(select(Site).where(Site.domain == domain))
    return result.scalar_one_or_none()


async def get_site_page_count(db: AsyncSession, site_id: uuid.UUID) -> int:
    result = await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))
    return result.scalar_one()


async def delete_site(
    db: AsyncSession,
    site_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> bool:
    site = await get_site_by_id(db, site_id, workspace_id)
    if not site:
        return False
    await db.delete(site)
    await db.commit()
    return True
