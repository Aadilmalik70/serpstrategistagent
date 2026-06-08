import asyncio
from sqlalchemy import text
from app.database import async_session_factory

async def main():
    async with async_session_factory() as db:
        # Check meta JSONB
        r = await db.execute(text(
            "SELECT meta FROM pages WHERE site_id='7800f7c3-c38e-43b8-8c86-0ee54a12c8d0' AND meta IS NOT NULL LIMIT 1"
        ))
        row = r.first()
        if row:
            print("META JSONB sample:", row[0])
        else:
            print("NO META DATA STORED in pages")

        # Check response_time_ms
        r2 = await db.execute(text(
            "SELECT path, response_time_ms, word_count, status_code FROM pages WHERE site_id='7800f7c3-c38e-43b8-8c86-0ee54a12c8d0' LIMIT 5"
        ))
        print("\nSample pages data:")
        for row in r2:
            print(f"  {row[0]} | status={row[3]} | {row[1]}ms | {row[2]} words")

        # Check issue categories/severities
        r3 = await db.execute(text(
            "SELECT severity, COUNT(*) FROM issues WHERE site_id='7800f7c3-c38e-43b8-8c86-0ee54a12c8d0' GROUP BY severity"
        ))
        print("\nIssue severity breakdown:")
        for row in r3:
            print(f"  {row[0]}: {row[1]}")

        r4 = await db.execute(text(
            "SELECT category, COUNT(*) FROM issues WHERE site_id='7800f7c3-c38e-43b8-8c86-0ee54a12c8d0' GROUP BY category"
        ))
        print("\nIssue category breakdown:")
        for row in r4:
            print(f"  {row[0]}: {row[1]}")

asyncio.run(main())
