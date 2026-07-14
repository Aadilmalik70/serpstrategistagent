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
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue
from app.models.page import Page

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
        self.images: list[dict[str, str]] = []
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


async def _resolve_public_host(hostname: str, port: int) -> None:
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
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise CrawlError("Private or reserved network targets are not allowed")


async def _validate_public_target(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CrawlError("Crawler target is not a valid HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise CrawlError("Crawler target cannot contain embedded credentials")
    await _resolve_public_host(
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


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
        await _validate_public_target(current)
        async with client.stream("GET", current) as response:
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
                final_url=str(response.url),
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
) -> tuple[list[str], dict[str, Any]]:
    settings = get_settings()
    pending = deque(robots.sitemaps or [urljoin(base_url, "/sitemap.xml")])
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []
    errors: list[str] = []

    while pending and len(seen_sitemaps) < settings.crawler_sitemap_limit and len(page_urls) < max_urls:
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


async def run_first_party_crawl(
    db: AsyncSession,
    site_id: uuid.UUID,
    domain: str,
    *,
    max_pages: int = 100,
    job_id: uuid.UUID | None = None,
) -> CrawlSnapshot:
    settings = get_settings()
    bounded_max_pages = max(1, min(int(max_pages), 100_000))
    snapshot = CrawlSnapshot(
        site_id=site_id,
        status="running",
        extracted_data={"adapter": "first_party", "phase": "starting"},
    )
    db.add(snapshot)
    await db.flush()
    if job_id:
        job = await db.get(JobQueue, job_id)
        if job:
            job.payload = {**(job.payload or {}), "snapshot_id": str(snapshot.id)}
    await db.commit()
    await db.refresh(snapshot)

    started = time.perf_counter()
    errors: list[dict[str, str]] = []
    blocked_by_robots = 0
    persisted_paths: set[str] = set()
    inlinks: dict[str, set[str]] = defaultdict(set)

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
        normalized_domain = _normalize_domain(domain)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
            homepage = await _resolve_homepage(client, normalized_domain)
            homepage_url = _normalize_url(homepage.final_url, homepage.final_url, normalized_domain)
            if not homepage_url:
                raise CrawlError("Resolved homepage is outside the configured domain")
            site_host = urlsplit(homepage_url).hostname or normalized_domain
            base_url = _origin(homepage_url)

            robots = await _load_robots(client, base_url, site_host)
            sitemap_urls, sitemap_summary = await _discover_sitemap_urls(
                client,
                base_url,
                site_host,
                robots,
                max_urls=max(bounded_max_pages * 3, bounded_max_pages),
            )

            queue: deque[str] = deque()
            discovered: set[str] = set()
            crawled: set[str] = set()
            prefetched: dict[str, FetchResult] = {homepage_url: homepage}

            def discover(url: str | None) -> None:
                if not url or url in discovered:
                    return
                if len(discovered) >= bounded_max_pages * 5:
                    return
                discovered.add(url)
                queue.append(url)

            discover(homepage_url)
            for sitemap_url in sitemap_urls:
                discover(sitemap_url)

            while queue and len(persisted_paths) < bounded_max_pages:
                batch: list[str] = []
                while queue and len(batch) < settings.crawler_concurrency:
                    candidate = queue.popleft()
                    if candidate in crawled:
                        continue
                    crawled.add(candidate)
                    if not robots.allowed(candidate, settings.crawler_user_agent):
                        blocked_by_robots += 1
                        continue
                    batch.append(candidate)

                if not batch:
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

                results = await asyncio.gather(*(fetch_one(url) for url in batch), return_exceptions=True)
                for requested_url, result in zip(batch, results):
                    if isinstance(result, BaseException):
                        errors.append({
                            "url": requested_url,
                            "type": type(result).__name__,
                            "message": str(result)[:500],
                        })
                        continue

                    final_url = _normalize_url(result.final_url, requested_url, site_host)
                    if not final_url:
                        errors.append({
                            "url": requested_url,
                            "type": "external_redirect",
                            "message": "Final response resolved outside the configured site",
                        })
                        continue
                    crawled.add(final_url)
                    path = _path_key(final_url)
                    content_type = result.headers.get("content-type", "").lower()
                    is_html = "text/html" in content_type or "application/xhtml+xml" in content_type
                    parser = PageHtmlParser()
                    if is_html and result.body:
                        parser.feed(result.body.decode("utf-8", errors="replace"))

                    internal_links: list[str] = []
                    external_links = 0
                    if is_html and "nofollow" not in parser.meta.get("robots", "").lower():
                        for href in parser.links:
                            normalized_link = _normalize_url(href, final_url, site_host)
                            if normalized_link:
                                target_path = _path_key(normalized_link)
                                if normalized_link not in internal_links:
                                    internal_links.append(normalized_link)
                                inlinks[target_path].add(path)
                                discover(normalized_link)
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
                            result.headers.get("x-robots-tag", ""),
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
                        "linked_from": sorted(inlinks.get(path, set())),
                        "h1_count": len(h1_values),
                        "h2": parser.headings("h2")[:50],
                        "h3": parser.headings("h3")[:50],
                        "images_count": len(parser.images),
                        "images_without_alt": sum(1 for image in parser.images if not image.get("alt")),
                        "lang": parser.html_lang,
                        "viewport": parser.meta.get("viewport"),
                        "robots": robots_directives,
                        "hreflang": parser.hreflang[:50],
                        "og_tags": og_tags,
                        "twitter_tags": twitter_tags,
                        "json_ld_count": parser.json_ld_count,
                    }
                    content_hash = hashlib.sha256(result.body).hexdigest()
                    await _upsert_page(
                        db,
                        site_id=site_id,
                        path=path,
                        title=parser.title,
                        meta_description=parser.meta.get("description"),
                        h1=h1_values[0] if h1_values else None,
                        status_code=result.status_code,
                        word_count=parser.word_count if is_html else 0,
                        response_time_ms=result.response_time_ms,
                        canonical_url=canonical,
                        content_hash=content_hash,
                        metadata=metadata,
                    )
                    persisted_paths.add(path)

                    if len(persisted_paths) >= bounded_max_pages:
                        break

                snapshot.pages_discovered = len(discovered)
                snapshot.pages_crawled = len(persisted_paths)
                snapshot.errors = len(errors)
                snapshot.extracted_data = {
                    "adapter": "first_party",
                    "phase": "crawling",
                    "base_url": base_url,
                    "robots_status": robots.status_code,
                    "sitemap_urls": sitemap_summary.get("sitemaps_checked", []),
                    "robots_blocked": blocked_by_robots,
                    "recent_errors": errors[-10:],
                }
                await db.commit()

                delay = max(settings.crawler_request_delay_ms / 1000, robots.crawl_delay)
                if delay:
                    await asyncio.sleep(delay)

            for target_path, sources in inlinks.items():
                page = await db.scalar(select(Page).where(Page.site_id == site_id, Page.path == target_path))
                if page:
                    page.meta = {**(page.meta or {}), "linked_from": sorted(sources)[:500]}

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            snapshot.pages_discovered = len(discovered)
            snapshot.pages_crawled = len(persisted_paths)
            snapshot.errors = len(errors)
            snapshot.completed_at = datetime.now(timezone.utc)
            snapshot.status = "completed" if persisted_paths else "failed"
            snapshot.extracted_data = {
                "adapter": "first_party",
                "phase": "completed" if persisted_paths else "failed",
                "base_url": base_url,
                "homepage_status": homepage.status_code,
                "robots": {
                    "url": robots.url,
                    "status_code": robots.status_code,
                    "error": robots.error,
                    "blocked_urls": blocked_by_robots,
                },
                "sitemap": sitemap_summary,
                "duration_ms": elapsed_ms,
                "max_pages": bounded_max_pages,
                "errors": errors[:50],
            }
            await db.commit()
            await db.refresh(snapshot)
            return snapshot

    except Exception as exc:
        logger.exception("First-party crawl failed for %s", domain)
        snapshot.status = "failed"
        snapshot.errors = max(snapshot.errors or 0, 1)
        snapshot.completed_at = datetime.now(timezone.utc)
        snapshot.extracted_data = {
            "adapter": "first_party",
            "phase": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        await db.commit()
        await db.refresh(snapshot)
        return snapshot
