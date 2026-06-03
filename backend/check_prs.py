import asyncio
import uuid
import httpx
from app.database import async_session_factory
from app.models.site import Site


async def main():
    async with async_session_factory() as db:
        site = await db.get(Site, uuid.UUID("b689d83e-ac0f-47aa-b786-716c2837788f"))
        token = site.github_token
        repo = site.github_repo

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=15) as c:
        for pr_num in [5, 6]:
            print(f"\n{'='*60}")
            print(f"PR #{pr_num}")
            print("=" * 60)

            r = await c.get(f"https://api.github.com/repos/{repo}/pulls/{pr_num}", headers=headers)
            pr = r.json()
            print(f"Title: {pr.get('title')}")
            print(f"State: {pr.get('state')}")
            print(f"Branch: {pr.get('head', {}).get('ref')}")
            print(f"Body: {(pr.get('body') or '')[:200]}")
            print()

            rf = await c.get(f"https://api.github.com/repos/{repo}/pulls/{pr_num}/files", headers=headers)
            for f in rf.json():
                fname = f.get("filename", "?")
                status = f.get("status", "?")
                patch = f.get("patch", "No patch available")
                print(f"--- {fname} ({status}) ---")
                print(patch[:1500])
                print()


asyncio.run(main())
