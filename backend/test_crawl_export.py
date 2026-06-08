"""Test sync_issues_from_export."""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")
from app.services.librecrawl import sync_issues_from_export


async def test():
    site_id = uuid.UUID("7800f7c3-c38e-43b8-8c86-0ee54a12c8d0")
    result = await sync_issues_from_export(site_id, crawl_id=7)
    print(f"Result: {result}")


asyncio.run(test())
