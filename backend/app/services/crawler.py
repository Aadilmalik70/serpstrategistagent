import uuid
import hashlib
import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page import Page
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue


async def run_crawl(db: AsyncSession, site_id: uuid.UUID, domain: str, max_pages: int = 100):
    """Crawl a domain, extract page metadata, and store results."""

    # Create crawl snapshot
    snapshot = CrawlSnapshot(site_id=site_id, status="running")
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    base_url = f"https://{domain}"
    discovered: set[str] = {"/"}
    crawled: set[str] = set()
    queue: list[str] = ["/"]
    errors = 0

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "SERPStrategistBot/0.1 (+https://serpstrategist.com)"},
    ) as client:
        while queue and len(crawled) < max_pages:
            path = queue.pop(0)
            if path in crawled:
                continue

            url = urljoin(base_url, path)
            start_time = time.time()

            try:
                resp = await client.get(url)
                response_time_ms = int((time.time() - start_time) * 1000)
                crawled.add(path)

                # Extract metadata from HTML
                html = resp.text
                title = _extract_tag(html, "title")
                meta_desc = _extract_meta(html, "description")
                h1 = _extract_tag(html, "h1")
                word_count = len(html.split()) if resp.status_code == 200 else 0
                content_hash = hashlib.sha256(html.encode()).hexdigest()

                # Extract internal links
                links = _extract_internal_links(html, domain)
                for link in links:
                    if link not in discovered and len(discovered) < max_pages * 2:
                        discovered.add(link)
                        queue.append(link)

                # Upsert page
                from sqlalchemy import select
                result = await db.execute(
                    select(Page).where(Page.site_id == site_id, Page.path == path)
                )
                existing_page = result.scalar_one_or_none()

                if existing_page:
                    existing_page.title = title
                    existing_page.meta_description = meta_desc
                    existing_page.h1 = h1
                    existing_page.status_code = resp.status_code
                    existing_page.word_count = word_count
                    existing_page.response_time_ms = response_time_ms
                    existing_page.content_hash = content_hash
                    existing_page.last_crawled_at = datetime.now(timezone.utc)
                else:
                    page = Page(
                        site_id=site_id,
                        path=path,
                        title=title,
                        meta_description=meta_desc,
                        h1=h1,
                        status_code=resp.status_code,
                        word_count=word_count,
                        response_time_ms=response_time_ms,
                        content_hash=content_hash,
                        last_crawled_at=datetime.now(timezone.utc),
                    )
                    db.add(page)

                # Update snapshot progress
                snapshot.pages_discovered = len(discovered)
                snapshot.pages_crawled = len(crawled)
                await db.commit()

            except Exception:
                errors += 1
                crawled.add(path)
                snapshot.errors = errors
                await db.commit()

            # Rate limit: 1 request/second
            await asyncio.sleep(1.0)

    # Mark complete
    snapshot.status = "completed"
    snapshot.completed_at = datetime.now(timezone.utc)
    snapshot.pages_discovered = len(discovered)
    snapshot.pages_crawled = len(crawled)
    snapshot.errors = errors
    await db.commit()

    return snapshot


def _extract_tag(html: str, tag: str) -> str | None:
    """Extract first occurrence of a tag's content."""
    import re
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip()[:500] if match else None


def _extract_meta(html: str, name: str) -> str | None:
    """Extract content of a meta tag by name."""
    import re
    match = re.search(
        rf'<meta\s+name=["\']?{name}["\']?\s+content=["\']([^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf'<meta\s+content=["\']([^"\']*)["\']?\s+name=["\']?{name}["\']?',
            html,
            re.IGNORECASE,
        )
    return match.group(1).strip()[:1000] if match else None


def _extract_internal_links(html: str, domain: str) -> list[str]:
    """Extract internal links as paths."""
    import re
    links = []
    for match in re.finditer(r'href=["\']([^"\'#]+)["\']', html, re.IGNORECASE):
        href = match.group(1)
        parsed = urlparse(href)

        # Skip external links, mailto, tel, javascript
        if parsed.scheme and parsed.scheme not in ("http", "https", ""):
            continue
        if parsed.netloc and parsed.netloc != domain:
            continue

        path = parsed.path or "/"
        if not path.startswith("/"):
            continue
        # Skip common non-page extensions
        if any(path.endswith(ext) for ext in (
            ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".xml",
            ".woff", ".woff2", ".ttf", ".eot", ".otf",
            ".ico", ".json", ".zip", ".gz", ".mp4", ".mp3", ".webp", ".avif",
        )):
            continue

        if path not in links:
            links.append(path)

    return links[:50]  # Limit links per page
