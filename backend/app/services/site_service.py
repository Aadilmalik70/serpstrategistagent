import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site import Site
from app.models.page import Page
from app.schemas.site import SiteCreate


async def create_site(db: AsyncSession, data: SiteCreate) -> Site:
    name = data.name or data.domain
    site = Site(domain=data.domain, name=name)
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


async def get_sites(db: AsyncSession) -> list[Site]:
    result = await db.execute(select(Site).order_by(Site.created_at.desc()))
    return list(result.scalars().all())


async def get_site_by_id(db: AsyncSession, site_id: uuid.UUID) -> Site | None:
    return await db.get(Site, site_id)


async def get_site_by_domain(db: AsyncSession, domain: str) -> Site | None:
    result = await db.execute(select(Site).where(Site.domain == domain))
    return result.scalar_one_or_none()


async def get_site_page_count(db: AsyncSession, site_id: uuid.UUID) -> int:
    result = await db.execute(select(func.count(Page.id)).where(Page.site_id == site_id))
    return result.scalar_one()


async def delete_site(db: AsyncSession, site_id: uuid.UUID) -> bool:
    site = await db.get(Site, site_id)
    if not site:
        return False
    await db.delete(site)
    await db.commit()
    return True
