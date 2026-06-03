import asyncio
from app.database import async_session_factory
from app.services.site_service import get_sites


async def main():
    async with async_session_factory() as db:
        sites = await get_sites(db)
        for s in sites:
            print(f"{s.domain} | updated_at={s.updated_at} | name={s.name}")


asyncio.run(main())
