from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import posixpath
import re
import socket
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import CrawlFrontier, JobQueue
from app.models.page import Page
from app.services.rendered_crawler import (
    AdaptivePacer,
    detect_bot_block,
    needs_javascript_render,
    render_url,
)

logger = logging.getLogger(__name__)

SKIPPED_EXTENSIONS = {
    ".7z", ".avi", ".avif", ".css", ".csv", ".doc", ".docx", ".eot",
    ".epub", ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".js", ".json",
    ".m4a", ".m4v", ".mov", ".mp3", ".mp4", ".mpeg", ".pdf", ".png",
    ".ppt", ".pptx", ".rar", ".rss", ".svg", ".tar", ".tgz", ".tif",
    ".tiff", ".ttf", ".txt", ".wav", ".webm", ".webp", ".woff", ".woff2",
    ".xls", ".xlsx", ".xml", ".zip",
}
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref_src",
    "igshid", "yclid", "vero_conv", "vero_id",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class CrawlError(RuntimeError):
    pass


class CrawlCancelled(CrawlError):
    pass


class CrawlLeaseLost(CrawlError):
    pass


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    response_time_ms: int
    redirect_chain: list[str]
    truncated: bool


@dataclass
class RobotsState:
    parser: RobotFileParser
    status_code: int | None
    url: str
    sitemaps: list[str]
    crawl_delay: float
    error: str | None = None

    def allowed(self, url: str, user_agent: str) -> bool:
        if self.status_code is None or self.status_code >= 400:
            return True
        try:
            return self.parser.can_fetch(user_agent, url)
        except Exception:
            return True


class PageHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._heading: str | None = None
        self._skip_depth = 0
        self._json_ld = False
        self.title_parts: list[str] = []
        self.heading_parts: dict[str, list[list[str]]] = {"h1": [], "h2": [], "h3": []}
        self.visible_text: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.links: list[str] = []
        self.images: list[dict[str, Any]] = []
        self.hreflang: list[dict[str, str]] = []
        self.html_lang: str | None = None
        self.json_ld_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): (value or "").strip() for key, value in attrs}
        if tag in {"style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        elif tag == "script":
            self._skip_depth += 1
            self._json_ld = values.get("type", "").lower() == "application/ld+json"
            if self._json_ld:
                self.json_ld_count += 1

        if tag == "html":
            self.html_lang = values.get("lang") or None
        elif tag == "title":
            self._in_title = True
        elif tag in self.heading_parts:
            self._heading = tag
            self.heading_parts[tag].append([])
        elif tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content")
            if key and content:
                self.meta[key] = content[:4000]
        elif tag == "link":
            rel = values.get("rel", "").lower().split()
            href = values.get("href")
            if href and "canonical" in rel:
                self.canonical = href
            if href and values.get("hreflang"):
                self.hreflang.append({"hreflang": values["hreflang"], "href": href})
        elif tag in {"a", "area"}:
            href = values.get("href")
            if href and len(self.links) < 1000:
                self.links.append(href)
        elif tag == "img" and len(self.images) < 250:
            self.images.append({
                "src": values.get("src", "")[:2048],
                "alt": values.get("alt", "")[:1000],
                "has_alt": "alt" in values,
            })

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag == self._heading:
            self._heading = None
        if tag in {"style", "noscript", "template", "svg", "script"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            if tag == "script":
                self._json_ld = False

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        if self._in_title:
            self.title_parts.append(clean)
        if self._heading and self.heading_parts[self._heading]:
            self.heading_parts[self._heading][-1].append(clean)
        if self._skip_depth == 0:
            self.visible_text.append(clean)

    @property
    def title(self) -> str | None:
        value = " ".join(self.title_parts).strip()
        return value[:512] or None

    def headings(self, tag: str) -> list[str]:
        values = [" ".join(parts).strip() for parts in self.heading_parts[tag]]
        return [value[:512] for value in values if value]

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b[\w'-]+\b", " ".join(self.visible_text)))


async def _resolve_public_host(hostname: str, port: int) -> str:
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            0,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise CrawlError("Website hostname could not be resolved") from exc
    addresses = {item[4][0] for item in results}
    if not addresses:
        raise CrawlError("Website hostname could not be resolved")
    normalized: list[str] = []
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if not parsed_address.is_global:
            raise CrawlError("Private or reserved network targets are not allowed")
        normalized.append(parsed_address.compressed)
    return sorted(normalized)[0]


async def _validate_public_target(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CrawlError("Crawler target is not a valid HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise CrawlError("Crawler target cannot contain embedded credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise CrawlError("Crawler targets must use port 80 or 443")
    return await _resolve_public_host(
        parsed.hostname,
        port,
    )


def _pinned_target_url(url: str, address: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise CrawlError("Crawler target hostname is missing")
    host = f"[{address}]" if ":" in address else address
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    is_default_port = (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    )
    netloc = host if is_default_port else f"{host}:{port}"
    original_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    host_header = original_host if is_default_port else f"{original_host}:{port}"
    pinned = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
    return pinned, parsed.hostname, host_header


def _normalize_domain(domain: str) -> str:
    raw = domain.strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if not parsed.hostname:
        raise CrawlError("Site domain is invalid")
    return parsed.hostname.lower().rstrip(".")


def _host_key(hostname: str) -> str:
    host = hostname.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _same_site(hostname: str | None, site_host: str) -> bool:
    return bool(hostname and _host_key(hostname) == _host_key(site_host))


def _normalize_url(raw: str, base_url: str, site_host: str) -> str | None:
    value = (raw or "").strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not _same_site(parsed.hostname, site_host):
        return None
    if parsed.username or parsed.password:
        return None

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    had_trailing_slash = path.endswith("/")
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = f"/{path}"
    if had_trailing_slash and path != "/":
        path = f"{path}/"
    if any(path.lower().endswith(extension) for extension in SKIPPED_EXTENSIONS):
        return None

    query_items = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        lower = key.lower()
        if lower.startswith("utm_") or lower in TRACKING_PARAMS:
            continue
        query_items.append((key, val))
    query_items.sort()

    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = hostname
    if port and not ((parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query_items, doseq=True), ""))


def _path_key(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.path or '/'}{'?' + parsed.query if parsed.query else ''}"


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


async def _fetch_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    site_host: str,
    max_bytes: int,
    max_redirects: int,
) -> FetchResult:
    current = url
    redirects: list[str] = []
    started = time.perf_counter()
    for _ in range(max_redirects + 1):
        address = await _validate_public_target(current)
        pinned_url, hostname, host_header = _pinned_target_url(current, address)
        async with client.stream(
            "GET",
            pinned_url,
            headers={"Host": host_header},
            extensions={"sni_hostname": hostname},
        ) as response:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise CrawlError("Website returned a redirect without a location")
                next_url = _normalize_url(location, current, site_host)
                if not next_url:
                    raise CrawlError("Website redirected outside the configured site")
                redirects.append(next_url)
                current = next_url
                continue

            body = bytearray()
            truncated = False
            async for chunk in response.aiter_bytes():
                remaining = max_bytes - len(body)
                if remaining <= 0:
                    truncated = True
                    break
                body.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
                    break
            elapsed = int((time.perf_counter() - started) * 1000)
            return FetchResult(
                requested_url=url,
                final_url=current,
                status_code=response.status_code,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=bytes(body),
                response_time_ms=elapsed,
                redirect_chain=redirects,
                truncated=truncated,
            )
    raise CrawlError("Website redirected too many times")


async def _resolve_homepage(client: httpx.AsyncClient, domain: str) -> FetchResult:
    settings = get_settings()
    errors: list[str] = []
    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}/"
        try:
            result = await _fetch_url(
                client,
                url,
                site_host=domain,
                max_bytes=settings.crawler_max_response_bytes,
                max_redirects=settings.crawler_max_redirects,
            )
            if result.status_code < 500:
                return result
            errors.append(f"{scheme.upper()} returned HTTP {result.status_code}")
        except (httpx.HTTPError, CrawlError) as exc:
            errors.append(f"{scheme.upper()}: {str(exc)[:200]}")
    raise CrawlError("Homepage could not be fetched. " + "; ".join(errors))


async def _load_robots(
    client: httpx.AsyncClient,
    base_url: str,
    site_host: str,
) -> RobotsState:
    settings = get_settings()
    robots_url = urljoin(base_url, "/robots.txt")
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = await _fetch_url(
            client,
            robots_url,
            site_host=site_host,
            max_bytes=min(settings.crawler_max_response_bytes, 512_000),
            max_redirects=settings.crawler_max_redirects,
        )
        text = response.body.decode("utf-8", errors="replace")
        sitemaps = []
        if response.status_code < 400:
            parser.parse(text.splitlines())
            for line in text.splitlines():
                if line.lower().startswith("sitemap:"):
                    value = line.split(":", 1)[1].strip()
                    normalized = _normalize_url(value, robots_url, site_host)
                    if normalized and normalized not in sitemaps:
                        sitemaps.append(normalized)
        delay = parser.crawl_delay(settings.crawler_user_agent) or parser.crawl_delay("*") or 0
        return RobotsState(
            parser=parser,
            status_code=response.status_code,
            url=response.final_url,
            sitemaps=sitemaps,
            crawl_delay=min(float(delay or 0), 5.0),
        )
    except (httpx.HTTPError, CrawlError) as exc:
        return RobotsState(
            parser=parser,
            status_code=None,
            url=robots_url,
            sitemaps=[],
            crawl_delay=0,
            error=str(exc)[:500],
        )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


async def _discover_sitemap_urls(
    client: httpx.AsyncClient,
    base_url: str,
    site_host: str,
    robots: RobotsState,
    max_urls: int,
    control: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    settings = get_settings()
    pending = deque(robots.sitemaps or [urljoin(base_url, "/sitemap.xml")])
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []
    errors: list[str] = []

    while pending and len(seen_sitemaps) < settings.crawler_sitemap_limit and len(page_urls) < max_urls:
        if control and await control():
            raise CrawlCancelled("Crawl cancellation requested")
        sitemap_url = pending.popleft()
        normalized_sitemap = _normalize_url(sitemap_url, base_url, site_host)
        if not normalized_sitemap or normalized_sitemap in seen_sitemaps:
            continue
        seen_sitemaps.add(normalized_sitemap)
        try:
            response = await _fetch_url(
                client,
                normalized_sitemap,
                site_host=site_host,
                max_bytes=settings.crawler_max_response_bytes,
                max_redirects=settings.crawler_max_redirects,
            )
            if response.status_code >= 400:
                errors.append(f"{normalized_sitemap}: HTTP {response.status_code}")
                continue
            root = ElementTree.fromstring(response.body)
            root_type = _local_name(root.tag)
            locations = [
                (element.text or "").strip()
                for element in root.iter()
                if _local_name(element.tag) == "loc" and (element.text or "").strip()
            ]
            if root_type == "sitemapindex":
                for location in locations:
                    child = _normalize_url(location, normalized_sitemap, site_host)
                    if child and child not in seen_sitemaps:
                        pending.append(child)
            else:
                for location in locations:
                    page = _normalize_url(location, normalized_sitemap, site_host)
                    if page and page not in page_urls:
                        page_urls.append(page)
                        if len(page_urls) >= max_urls:
                            break
        except (ElementTree.ParseError, httpx.HTTPError, CrawlError) as exc:
            errors.append(f"{normalized_sitemap}: {str(exc)[:200]}")

    return page_urls, {
        "sitemaps_checked": sorted(seen_sitemaps),
        "urls_discovered": len(page_urls),
        "errors": errors[:20],
    }


async def _upsert_page(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    path: str,
    title: str | None,
    meta_description: str | None,
    h1: str | None,
    status_code: int,
    word_count: int,
    response_time_ms: int,
    canonical_url: str | None,
    content_hash: str,
    metadata: dict[str, Any],
) -> Page:
    page = await db.scalar(select(Page).where(Page.site_id == site_id, Page.path == path))
    if page is None:
        page = Page(site_id=site_id, path=path)
        db.add(page)
    page.title = title
    page.meta_description = meta_description
    page.h1 = h1
    page.status_code = status_code
    page.word_count = word_count
    page.response_time_ms = response_time_ms
    page.canonical_url = canonical_url
    page.content_hash = content_hash
    page.meta = metadata
    page.last_crawled_at = datetime.now(timezone.utc)
    return page


def _frontier_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


async def _add_frontier_urls(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    urls: list[tuple[str, str | None]],
    max_urls: int,
) -> int:
    unique: dict[str, tuple[str, str | None]] = {}
    for url, discovered_from in urls:
        unique.setdefault(_frontier_hash(url), (url, discovered_from))
    if not unique:
        return 0

    existing_rows: list[CrawlFrontier] = []
    hashes = list(unique)
    # Stay comfortably below PostgreSQL/asyncpg bind limits for large sitemaps.
    for offset in range(0, len(hashes), 5_000):
        existing_rows.extend(
            list(
                (
                    await db.execute(
                        select(CrawlFrontier).where(
                            CrawlFrontier.job_id == job_id,
                            CrawlFrontier.url_hash.in_(hashes[offset : offset + 5_000]),
                        )
                    )
                ).scalars().all()
            )
        )
    existing = {row.url_hash: row.url for row in existing_rows}
    for url_hash, (url, _) in unique.items():
        if url_hash in existing and existing[url_hash] != url:
            raise CrawlError("Crawler frontier URL hash collision")

    total = int(
        await db.scalar(
            select(func.count(CrawlFrontier.id)).where(CrawlFrontier.job_id == job_id)
        )
        or 0
    )
    remaining = max(0, max_urls - total)
    added = 0
    for url_hash, (url, discovered_from) in unique.items():
        if url_hash in existing or added >= remaining:
            continue
        db.add(
            CrawlFrontier(
                job_id=job_id,
                url=url,
                url_hash=url_hash,
                status="queued",
                discovered_from=discovered_from,
            )
        )
        added += 1
        if added % 1_000 == 0:
            await db.flush()
    if added:
        await db.flush()
    return added


async def _next_frontier_batch(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    limit: int,
) -> list[CrawlFrontier]:
    rows = list(
        (
            await db.execute(
                select(CrawlFrontier)
                .where(CrawlFrontier.job_id == job_id, CrawlFrontier.status == "queued")
                .order_by(CrawlFrontier.created_at.asc(), CrawlFrontier.id.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).scalars().all()
    )
    for row in rows:
        row.status = "fetching"
        row.attempt_count += 1
    if rows:
        await db.commit()
    return rows


async def _frontier_counts(db: AsyncSession, job_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await db.execute(
            select(CrawlFrontier.status, func.count(CrawlFrontier.id))
            .where(CrawlFrontier.job_id == job_id)
            .group_by(CrawlFrontier.status)
        )
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    counts["total"] = sum(counts.values())
    return counts


async def _pages_crawled_for_snapshot(db: AsyncSession, snapshot: CrawlSnapshot) -> int:
    return int(
        await db.scalar(
            select(func.count(Page.id)).where(
                Page.site_id == snapshot.site_id,
                Page.last_crawled_at.is_not(None),
                Page.last_crawled_at >= snapshot.started_at,
            )
        )
        or 0
    )


async def _rebuild_linked_from(db: AsyncSession, site_id: uuid.UUID) -> None:
    pages = list(
        (await db.execute(select(Page).where(Page.site_id == site_id))).scalars().all()
    )
    inlinks: dict[str, set[str]] = defaultdict(set)
    for page in pages:
        links = (page.meta or {}).get("internal_links", [])
        if not isinstance(links, list):
            continue
        for target in links:
            if isinstance(target, str):
                inlinks[target].add(page.path)
    for page in pages:
        page.meta = {**(page.meta or {}), "linked_from": sorted(inlinks.get(page.path, set()))[:500]}


async def _crawl_snapshot_for_job(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    job_id: uuid.UUID,
) -> CrawlSnapshot:
    job = await db.get(JobQueue, job_id)
    if not job:
        raise CrawlError("Crawl job no longer exists")
    snapshot: CrawlSnapshot | None = None
    raw_snapshot_id = (job.payload or {}).get("snapshot_id")
    if raw_snapshot_id:
        try:
            snapshot = await db.get(CrawlSnapshot, uuid.UUID(str(raw_snapshot_id)))
        except (TypeError, ValueError):
            snapshot = None
    if snapshot is not None and snapshot.site_id != site_id:
        raise CrawlError("Crawl snapshot does not belong to this site")
    if snapshot is None:
        snapshot = CrawlSnapshot(
            site_id=site_id,
            status="running",
            extracted_data={"adapter": "first_party", "phase": "starting"},
        )
        db.add(snapshot)
        await db.flush()
        job.payload = {**(job.payload or {}), "snapshot_id": str(snapshot.id)}
    else:
        snapshot.status = "running"
        snapshot.completed_at = None
        snapshot.extracted_data = {
            **(snapshot.extracted_data or {}),
            "adapter": "first_party",
            "phase": "resuming",
        }
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def run_first_party_crawl(
    db: AsyncSession,
    site_id: uuid.UUID,
    domain: str,
    *,
    max_pages: int = 100,
    job_id: uuid.UUID | None = None,
    control: Callable[[], Awaitable[bool]] | None = None,
) -> CrawlSnapshot:
    if not job_id:
        raise CrawlError("Durable first-party crawls require a persisted crawl job")
    settings = get_settings()
    bounded_max_pages = max(1, min(int(max_pages), 100_000))
    frontier_limit = max(bounded_max_pages * 5, bounded_max_pages)
    snapshot = await _crawl_snapshot_for_job(db, site_id=site_id, job_id=job_id)
    rendered_pages = 0
    render_attempts = 0
    device_comparisons = 0
    device_comparison_attempts = 0
    bot_blocks: list[dict[str, Any]] = []
    render_errors: list[dict[str, str]] = []

    started = time.perf_counter()

    timeout = httpx.Timeout(
        settings.crawler_timeout_seconds,
        connect=settings.crawler_connect_timeout_seconds,
    )
    headers = {
        "User-Agent": settings.crawler_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1",
        "Accept-Language": "en-US,en;q=0.8",
    }

    try:
        if control and await control():
            raise CrawlCancelled("Crawl cancellation requested")
        normalized_domain = _normalize_domain(domain)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
            limits=httpx.Limits(
                max_connections=max(4, settings.crawler_concurrency * 2),
                max_keepalive_connections=max(1, settings.crawler_concurrency),
                keepalive_expiry=10,
            ),
        ) as client:
            homepage = await _resolve_homepage(client, normalized_domain)
            if control and await control():
                raise CrawlCancelled("Crawl cancellation requested")
            homepage_url = _normalize_url(homepage.final_url, homepage.final_url, normalized_domain)
            if not homepage_url:
                raise CrawlError("Resolved homepage is outside the configured domain")
            site_host = urlsplit(homepage_url).hostname or normalized_domain
            base_url = _origin(homepage_url)

            robots = await _load_robots(client, base_url, site_host)
            pacer = AdaptivePacer(
                base_delay_seconds=max(
                    settings.crawler_request_delay_ms / 1000,
                    robots.crawl_delay,
                ),
                max_delay_seconds=settings.crawler_adaptive_max_delay_seconds,
            )
            if control and await control():
                raise CrawlCancelled("Crawl cancellation requested")
            sitemap_urls, sitemap_summary = await _discover_sitemap_urls(
                client,
                base_url,
                site_host,
                robots,
                max_urls=max(bounded_max_pages * 3, bounded_max_pages),
                control=control,
            )

            prefetched: dict[str, FetchResult] = {homepage_url: homepage}
            await _add_frontier_urls(
                db,
                job_id=job_id,
                urls=[(homepage_url, None), *((url, "sitemap") for url in sitemap_urls)],
                max_urls=frontier_limit,
            )
            await db.commit()

            while True:
                if control and await control():
                    raise CrawlCancelled("Crawl cancellation requested")
                pages_crawled = await _pages_crawled_for_snapshot(db, snapshot)
                if pages_crawled >= bounded_max_pages:
                    break
                frontier_rows = await _next_frontier_batch(
                    db,
                    job_id=job_id,
                    limit=min(
                        1
                        if robots.crawl_delay > 0
                        else pacer.concurrency(settings.crawler_concurrency),
                        bounded_max_pages - pages_crawled,
                    ),
                )
                if not frontier_rows:
                    break

                allowed_rows: list[CrawlFrontier] = []
                for frontier in frontier_rows:
                    if robots.allowed(frontier.url, settings.crawler_user_agent):
                        allowed_rows.append(frontier)
                    else:
                        frontier.status = "blocked"
                        frontier.completed_at = datetime.now(timezone.utc)
                if not allowed_rows:
                    await db.commit()
                    continue

                async def fetch_one(url: str) -> FetchResult:
                    if url in prefetched:
                        return prefetched.pop(url)
                    last_error: Exception | None = None
                    for attempt in range(2):
                        try:
                            return await _fetch_url(
                                client,
                                url,
                                site_host=site_host,
                                max_bytes=settings.crawler_max_response_bytes,
                                max_redirects=settings.crawler_max_redirects,
                            )
                        except (httpx.HTTPError, CrawlError) as exc:
                            last_error = exc
                            if attempt == 0:
                                await asyncio.sleep(0.25)
                    raise last_error or CrawlError("Page fetch failed")

                results = await asyncio.gather(
                    *(fetch_one(frontier.url) for frontier in allowed_rows),
                    return_exceptions=True,
                )
                if control and await control():
                    raise CrawlCancelled("Crawl cancellation requested")
                for frontier, result in zip(allowed_rows, results):
                    requested_url = frontier.url
                    if isinstance(result, BaseException):
                        frontier.status = "failed"
                        frontier.last_error = f"{type(result).__name__}: {str(result)[:1500]}"
                        frontier.completed_at = datetime.now(timezone.utc)
                        continue

                    final_url = _normalize_url(result.final_url, requested_url, site_host)
                    if not final_url:
                        frontier.status = "failed"
                        frontier.last_error = "Final response resolved outside the configured site"
                        frontier.completed_at = datetime.now(timezone.utc)
                        continue
                    block = detect_bot_block(result.status_code, result.headers, result.body)
                    pacer.record(status_code=result.status_code, bot_blocked=block.detected)
                    pacer.respect_retry_after(result.headers.get("retry-after"))
                    if block.detected:
                        bot_blocks.append(
                            {
                                "url": requested_url,
                                "status_code": result.status_code,
                                "provider": block.provider,
                                "reason": block.reason,
                            }
                        )
                        frontier.last_error = block.reason
                        if frontier.attempt_count < 3:
                            frontier.status = "queued"
                        else:
                            frontier.status = "blocked"
                            frontier.completed_at = datetime.now(timezone.utc)
                        continue
                    if result.status_code == 429:
                        frontier.last_error = "HTTP 429: origin rate limit"
                        if frontier.attempt_count < 3:
                            frontier.status = "queued"
                        else:
                            frontier.status = "failed"
                            frontier.completed_at = datetime.now(timezone.utc)
                        continue
                    content_type = result.headers.get("content-type", "").lower()
                    effective_status_code = result.status_code
                    effective_response_time_ms = result.response_time_ms
                    effective_headers = result.headers
                    is_html = "text/html" in content_type or "application/xhtml+xml" in content_type
                    parser = PageHtmlParser()
                    html_text = result.body.decode("utf-8", errors="replace") if is_html else ""
                    static_html_text = html_text
                    if is_html and result.body:
                        parser.feed(html_text)

                    render_metadata: dict[str, Any] = {
                        "used": False,
                        "triggered": False,
                        "device": None,
                    }
                    mobile_parser: PageHtmlParser | None = None
                    mobile_status_code: int | None = None
                    if (
                        settings.crawler_render_enabled
                        and render_attempts < settings.crawler_render_max_pages
                        and result.status_code < 400
                        and is_html
                        and needs_javascript_render(html_text, word_count=parser.word_count)
                    ):
                        render_metadata["triggered"] = True
                        render_attempts += 1
                        try:
                            rendered = await asyncio.wait_for(
                                render_url(
                                    final_url,
                                    user_agent=settings.crawler_user_agent,
                                    timeout_seconds=settings.crawler_render_timeout_seconds,
                                    mobile=False,
                                    validate_url=_validate_public_target,
                                    max_html_bytes=settings.crawler_max_response_bytes,
                                    source_html=static_html_text,
                                ),
                                timeout=settings.crawler_render_timeout_seconds + 5,
                            )
                            rendered_block = detect_bot_block(
                                rendered.status_code,
                                rendered.headers,
                                rendered.html,
                            )
                            pacer.record(
                                status_code=rendered.status_code,
                                bot_blocked=rendered_block.detected,
                            )
                            if rendered_block.detected:
                                bot_blocks.append(
                                    {
                                        "url": rendered.url,
                                        "status_code": rendered.status_code,
                                        "provider": rendered_block.provider,
                                        "reason": rendered_block.reason,
                                    }
                                )
                            else:
                                normalized_rendered_url = _normalize_url(
                                    rendered.url,
                                    final_url,
                                    site_host,
                                )
                                if not normalized_rendered_url:
                                    raise CrawlError("Rendered page resolved outside the configured site")
                                rendered_parser = PageHtmlParser()
                                rendered_parser.feed(rendered.html)
                                materially_improved = bool(
                                    (
                                        rendered_parser.word_count
                                        >= max(parser.word_count + 20, int(parser.word_count * 1.25))
                                        or (not parser.title and bool(rendered_parser.title))
                                        or (
                                            not parser.headings("h1")
                                            and bool(rendered_parser.headings("h1"))
                                        )
                                    )
                                    and rendered_parser.word_count >= parser.word_count
                                    and (not parser.title or bool(rendered_parser.title))
                                    and (
                                        not parser.headings("h1")
                                        or bool(rendered_parser.headings("h1"))
                                    )
                                    and (not parser.canonical or bool(rendered_parser.canonical))
                                    and (
                                        not parser.links
                                        or len(rendered_parser.links) >= max(1, len(parser.links) // 2)
                                    )
                                )
                                if materially_improved:
                                    final_url = normalized_rendered_url
                                    html_text = rendered.html
                                    parser = rendered_parser
                                    rendered_pages += 1
                                    render_metadata = {
                                        "used": True,
                                        "triggered": True,
                                        "device": "desktop",
                                        "status_code": rendered.status_code,
                                        "response_time_ms": rendered.response_time_ms,
                                    }
                                else:
                                    render_metadata["reason"] = "rendered_dom_not_materially_better"
                                if (
                                    materially_improved
                                    and device_comparison_attempts
                                    < settings.crawler_device_compare_max_pages
                                ):
                                    device_comparison_attempts += 1
                                    mobile = await asyncio.wait_for(
                                        render_url(
                                            final_url,
                                            user_agent=settings.crawler_user_agent,
                                            timeout_seconds=settings.crawler_render_timeout_seconds,
                                            mobile=True,
                                            validate_url=_validate_public_target,
                                            max_html_bytes=settings.crawler_max_response_bytes,
                                            source_html=static_html_text,
                                        ),
                                        timeout=settings.crawler_render_timeout_seconds + 5,
                                    )
                                    mobile_block = detect_bot_block(
                                        mobile.status_code,
                                        mobile.headers,
                                        mobile.html,
                                    )
                                    if not mobile_block.detected:
                                        mobile_parser = PageHtmlParser()
                                        mobile_parser.feed(mobile.html)
                                        mobile_status_code = mobile.status_code
                                        device_comparisons += 1
                        except Exception as exc:
                            message = f"{type(exc).__name__}: {str(exc)[:300]}"
                            render_metadata["error"] = message
                            render_errors.append({"url": final_url, "message": message})

                    path = _path_key(final_url)
                    internal_links: list[str] = []
                    external_links = 0
                    discovered_links: list[tuple[str, str | None]] = []
                    if is_html and "nofollow" not in parser.meta.get("robots", "").lower():
                        for href in parser.links:
                            normalized_link = _normalize_url(href, final_url, site_host)
                            if normalized_link:
                                target_path = _path_key(normalized_link)
                                if normalized_link not in internal_links:
                                    internal_links.append(normalized_link)
                                discovered_links.append((normalized_link, path))
                            else:
                                absolute = urljoin(final_url, href)
                                parsed_link = urlsplit(absolute)
                                if parsed_link.scheme in {"http", "https"} and parsed_link.hostname:
                                    external_links += 1

                    canonical = urljoin(final_url, parser.canonical) if parser.canonical else None
                    h1_values = parser.headings("h1")
                    og_tags = {key: value for key, value in parser.meta.items() if key.startswith("og:")}
                    twitter_tags = {key: value for key, value in parser.meta.items() if key.startswith("twitter:")}
                    robots_directives = ", ".join(
                        value for value in (
                            parser.meta.get("robots", ""),
                            effective_headers.get("x-robots-tag", ""),
                        ) if value
                    )
                    metadata = {
                        "crawler": "first_party",
                        "final_url": final_url,
                        "content_type": content_type,
                        "redirect_chain": result.redirect_chain,
                        "response_truncated": result.truncated,
                        "internal_links": [_path_key(url) for url in internal_links[:250]],
                        "internal_links_count": len(internal_links),
                        "external_links_count": external_links,
                        "linked_from": [],
                        "h1_count": len(h1_values),
                        "h2": parser.headings("h2")[:50],
                        "h3": parser.headings("h3")[:50],
                        "images_count": len(parser.images),
                        "images_without_alt": sum(
                            1 for image in parser.images if not image.get("has_alt")
                        ),
                        "lang": parser.html_lang,
                        "viewport": parser.meta.get("viewport"),
                        "robots": robots_directives,
                        "hreflang": parser.hreflang[:50],
                        "og_tags": og_tags,
                        "twitter_tags": twitter_tags,
                        "json_ld_count": parser.json_ld_count,
                        "rendering": render_metadata,
                    }
                    if mobile_parser is not None:
                        mobile_h1 = mobile_parser.headings("h1")
                        metadata["device_comparison"] = {
                            "desktop": {
                                "status_code": render_metadata.get("status_code"),
                                "title": parser.title,
                                "h1": h1_values[0] if h1_values else None,
                                "word_count": parser.word_count,
                                "links": len(parser.links),
                                "canonical": parser.canonical,
                                "meta_description": parser.meta.get("description"),
                                "robots": parser.meta.get("robots"),
                            },
                            "mobile": {
                                "status_code": mobile_status_code,
                                "title": mobile_parser.title,
                                "h1": mobile_h1[0] if mobile_h1 else None,
                                "word_count": mobile_parser.word_count,
                                "links": len(mobile_parser.links),
                                "canonical": mobile_parser.canonical,
                                "meta_description": mobile_parser.meta.get("description"),
                                "robots": mobile_parser.meta.get("robots"),
                            },
                            "different": bool(
                                render_metadata.get("status_code") != mobile_status_code
                                or parser.title != mobile_parser.title
                                or (h1_values[0] if h1_values else None)
                                != (mobile_h1[0] if mobile_h1 else None)
                                or parser.word_count != mobile_parser.word_count
                                or len(parser.links) != len(mobile_parser.links)
                                or parser.canonical != mobile_parser.canonical
                                or parser.meta.get("description") != mobile_parser.meta.get("description")
                                or parser.meta.get("robots") != mobile_parser.meta.get("robots")
                            ),
                        }
                    content_hash = hashlib.sha256(html_text.encode("utf-8") if is_html else result.body).hexdigest()
                    await _upsert_page(
                        db,
                        site_id=site_id,
                        path=path,
                        title=parser.title,
                        meta_description=parser.meta.get("description"),
                        h1=h1_values[0] if h1_values else None,
                        status_code=effective_status_code,
                        word_count=parser.word_count if is_html else 0,
                        response_time_ms=effective_response_time_ms,
                        canonical_url=canonical,
                        content_hash=content_hash,
                        metadata=metadata,
                    )
                    await _add_frontier_urls(
                        db,
                        job_id=job_id,
                        urls=discovered_links,
                        max_urls=frontier_limit,
                    )
                    frontier.status = "completed"
                    frontier.last_error = None
                    frontier.completed_at = datetime.now(timezone.utc)

                counts = await _frontier_counts(db, job_id)
                pages_crawled = await _pages_crawled_for_snapshot(db, snapshot)
                snapshot.pages_discovered = counts.get("total", 0)
                snapshot.pages_crawled = pages_crawled
                snapshot.errors = counts.get("failed", 0)
                snapshot.extracted_data = {
                    "adapter": "first_party",
                    "phase": "crawling",
                    "base_url": base_url,
                    "robots_status": robots.status_code,
                    "sitemap_urls": sitemap_summary.get("sitemaps_checked", []),
                    "frontier": counts,
                    "rendering": {
                        "rendered_pages": rendered_pages,
                        "render_attempts": render_attempts,
                        "device_comparisons": device_comparisons,
                        "device_comparison_attempts": device_comparison_attempts,
                        "errors": len(render_errors),
                    },
                    "bot_protection": {
                        "events": len(bot_blocks),
                        "adaptive_delay_seconds": pacer.delay_seconds,
                        "adaptive_concurrency": pacer.concurrency(settings.crawler_concurrency),
                    },
                }
                await db.commit()

                if control and await control():
                    raise CrawlCancelled("Crawl cancellation requested")

                delay = pacer.delay_seconds
                if delay:
                    await asyncio.sleep(delay)

            if control and await control():
                raise CrawlCancelled("Crawl cancellation requested")
            await _rebuild_linked_from(db, site_id)
            counts = await _frontier_counts(db, job_id)
            pages_crawled = await _pages_crawled_for_snapshot(db, snapshot)
            if pages_crawled >= bounded_max_pages:
                queued_rows = list(
                    (
                        await db.execute(
                            select(CrawlFrontier).where(
                                CrawlFrontier.job_id == job_id,
                                CrawlFrontier.status == "queued",
                            )
                        )
                    ).scalars().all()
                )
                for row in queued_rows:
                    row.status = "deferred"
                if queued_rows:
                    await db.flush()
                counts = await _frontier_counts(db, job_id)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            snapshot.pages_discovered = counts.get("total", 0)
            snapshot.pages_crawled = pages_crawled
            snapshot.errors = counts.get("failed", 0)
            snapshot.completed_at = datetime.now(timezone.utc)
            snapshot.status = "completed" if pages_crawled else "failed"
            snapshot.extracted_data = {
                "adapter": "first_party",
                "phase": "completed" if pages_crawled else "failed",
                "base_url": base_url,
                "homepage_status": homepage.status_code,
                "robots": {
                    "url": robots.url,
                    "status_code": robots.status_code,
                    "error": robots.error,
                    "blocked_urls": counts.get("blocked", 0),
                },
                "sitemap": sitemap_summary,
                "frontier": counts,
                "duration_ms": elapsed_ms,
                "max_pages": bounded_max_pages,
                "rendering": {
                    "enabled": settings.crawler_render_enabled,
                    "rendered_pages": rendered_pages,
                    "render_attempts": render_attempts,
                    "device_comparisons": device_comparisons,
                    "device_comparison_attempts": device_comparison_attempts,
                    "errors": render_errors[:20],
                },
                "bot_protection": {
                    "events": bot_blocks[:50],
                    "throttle_events": pacer.throttle_events,
                    "final_delay_seconds": pacer.delay_seconds,
                    "final_concurrency": pacer.concurrency(settings.crawler_concurrency),
                },
                "errors": [
                    {"url": row.url, "message": row.last_error}
                    for row in list(
                        (
                            await db.execute(
                                select(CrawlFrontier)
                                .where(
                                    CrawlFrontier.job_id == job_id,
                                    CrawlFrontier.status == "failed",
                                )
                                .order_by(CrawlFrontier.updated_at.desc())
                                .limit(50)
                            )
                        ).scalars().all()
                    )
                ],
            }
            if control and await control():
                raise CrawlCancelled("Crawl cancellation requested")
            await db.commit()
            await db.refresh(snapshot)
            return snapshot

    except CrawlLeaseLost:
        raise
    except CrawlCancelled as exc:
        counts = await _frontier_counts(db, job_id)
        snapshot.status = "cancelled"
        snapshot.pages_discovered = counts.get("total", 0)
        snapshot.pages_crawled = await _pages_crawled_for_snapshot(db, snapshot)
        snapshot.errors = counts.get("failed", 0)
        snapshot.completed_at = datetime.now(timezone.utc)
        snapshot.extracted_data = {
            **(snapshot.extracted_data or {}),
            "adapter": "first_party",
            "phase": "cancelled",
            "frontier": counts,
            "error": str(exc),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        await db.commit()
        await db.refresh(snapshot)
        return snapshot
    except Exception as exc:
        logger.exception("First-party crawl failed for %s", domain)
        counts = await _frontier_counts(db, job_id)
        snapshot.status = "failed"
        snapshot.pages_discovered = counts.get("total", 0)
        snapshot.pages_crawled = await _pages_crawled_for_snapshot(db, snapshot)
        snapshot.errors = max(counts.get("failed", 0), 1)
        snapshot.completed_at = datetime.now(timezone.utc)
        snapshot.extracted_data = {
            "adapter": "first_party",
            "phase": "failed",
            "frontier": counts,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        await db.commit()
        await db.refresh(snapshot)
        return snapshot
