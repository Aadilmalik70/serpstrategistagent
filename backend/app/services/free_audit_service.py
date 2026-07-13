from __future__ import annotations

import asyncio
import hashlib
import hmac
from html.parser import HTMLParser
import ipaddress
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse
import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.free_audit import FreeAuditRequest
from app.schemas.free_audit import FreeAuditCreate, FreeAuditFinding, FreeAuditResponse


class FreeAuditServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class AuditHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.h1_count = 0
        self.html_lang: str | None = None
        self.json_ld_count = 0

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): (value or "").strip() for key, value in attrs}
        if tag == "html":
            self.html_lang = values.get("lang") or None
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            if key and values.get("content"):
                self.meta[key] = values["content"]
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href") or None
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self.json_ld_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


def requester_fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def audit_response(audit: FreeAuditRequest) -> FreeAuditResponse:
    return FreeAuditResponse(
        token=audit.public_token,
        status=audit.status,
        website=audit.normalized_url,
        domain=audit.domain,
        score=audit.score,
        summary=audit.summary or {},
        findings=[FreeAuditFinding.model_validate(item) for item in (audit.findings or [])],
        error_code=audit.error_code,
        created_at=audit.created_at,
        started_at=audit.started_at,
        completed_at=audit.completed_at,
        retry_after_seconds=2 if audit.status in {"queued", "running"} else None,
    )


async def create_free_audit(
    db: AsyncSession,
    data: FreeAuditCreate,
    *,
    requester_hash: str | None,
    user_agent: str | None,
) -> FreeAuditRequest:
    parsed = urlparse(data.website)
    domain = (parsed.hostname or "").lower()
    if not domain:
        raise FreeAuditServiceError("Enter a valid public website URL")

    now = datetime.now(timezone.utc)
    duplicate = await db.scalar(
        select(FreeAuditRequest)
        .where(
            FreeAuditRequest.email == data.email,
            FreeAuditRequest.domain == domain,
            FreeAuditRequest.created_at >= now - timedelta(hours=6),
            FreeAuditRequest.status.in_(["queued", "running", "completed"]),
        )
        .order_by(FreeAuditRequest.created_at.desc())
    )
    if duplicate:
        return duplicate

    if requester_hash:
        recent_count = await db.scalar(
            select(func.count(FreeAuditRequest.id)).where(
                FreeAuditRequest.requester_hash == requester_hash,
                FreeAuditRequest.created_at >= now - timedelta(days=1),
            )
        )
        if int(recent_count or 0) >= 5:
            raise FreeAuditServiceError("Daily free-audit limit reached. Try again tomorrow.", 429)

    audit = FreeAuditRequest(
        public_token=secrets.token_urlsafe(24),
        email=data.email,
        normalized_url=data.website,
        domain=domain,
        requester_hash=requester_hash,
        user_agent=(user_agent or "")[:500] or None,
        status="queued",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(audit)
    return audit


async def get_free_audit(db: AsyncSession, token: str) -> FreeAuditRequest | None:
    return await db.scalar(
        select(FreeAuditRequest).where(FreeAuditRequest.public_token == token)
    )


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
        raise FreeAuditServiceError("Website hostname could not be resolved", 422) from exc

    addresses = {item[4][0] for item in results}
    if not addresses:
        raise FreeAuditServiceError("Website hostname could not be resolved", 422)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise FreeAuditServiceError("Private or reserved network targets are not allowed", 422)


async def _validate_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FreeAuditServiceError("Website URL is invalid", 422)
    if parsed.username or parsed.password:
        raise FreeAuditServiceError("Website URL cannot contain credentials", 422)
    await _resolve_public_host(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


async def _fetch_html(url: str) -> tuple[str, int, dict[str, str], bytes, int]:
    settings = get_settings()
    timeout = httpx.Timeout(15.0, connect=5.0)
    headers = {
        "User-Agent": "SERPStrategists-FreeAudit/1.0 (+https://serpstrategists.com)",
        "Accept": "text/html,application/xhtml+xml",
    }
    current = url
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            await _validate_target(current)
            async with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise FreeAuditServiceError("Website returned an invalid redirect", 422)
                    current = urljoin(current, location)
                    continue

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        break
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return (
                    str(response.url),
                    response.status_code,
                    {key.lower(): value for key, value in response.headers.items()},
                    bytes(body),
                    elapsed_ms,
                )
    raise FreeAuditServiceError("Website redirected too many times", 422)


async def _probe(url: str) -> int | None:
    try:
        await _validate_target(url)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0),
            follow_redirects=False,
            headers={"User-Agent": "SERPStrategists-FreeAudit/1.0"},
        ) as client:
            async with client.stream("GET", url) as response:
                return response.status_code
    except (httpx.HTTPError, FreeAuditServiceError):
        return None


def _finding(
    code: str,
    title: str,
    severity: str,
    description: str,
    evidence: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "severity": severity,
        "description": description,
        "evidence": evidence,
    }


def build_report(
    *,
    requested_url: str,
    final_url: str,
    status_code: int,
    headers: dict[str, str],
    body: bytes,
    response_time_ms: int,
    robots_status: int | None,
    sitemap_status: int | None,
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    content_type = headers.get("content-type", "")
    findings: list[dict[str, Any]] = []
    parser = AuditHtmlParser()
    html = body.decode("utf-8", errors="replace")
    parser.feed(html)

    if status_code >= 500:
        findings.append(_finding("http_5xx", "Homepage returns a server error", "critical", "Search engines and users cannot reliably access the page.", str(status_code)))
    elif status_code >= 400:
        findings.append(_finding("http_4xx", "Homepage returns a client error", "critical", "The submitted homepage is not accessible.", str(status_code)))
    elif status_code >= 300:
        findings.append(_finding("http_redirect", "Homepage redirect was not resolved", "high", "The page returned an unresolved redirect.", str(status_code)))

    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        findings.append(_finding("non_html", "Homepage is not served as HTML", "high", "The response content type may prevent normal page indexing.", content_type or "missing content-type"))

    if urlparse(final_url).scheme != "https":
        findings.append(_finding("https_missing", "HTTPS is not enforced", "high", "Serve and redirect the site to a secure HTTPS URL.", final_url))

    title = parser.title
    if not title:
        findings.append(_finding("title_missing", "Page title is missing", "high", "Add a unique, descriptive title element to the homepage."))
    elif len(title) < 30 or len(title) > 65:
        findings.append(_finding("title_length", "Page title length needs attention", "low", "Aim for a concise title that communicates the primary topic.", f"{len(title)} characters"))

    description = parser.meta.get("description", "")
    if not description:
        findings.append(_finding("description_missing", "Meta description is missing", "medium", "Add a useful summary that supports search-result messaging."))
    elif len(description) < 100 or len(description) > 170:
        findings.append(_finding("description_length", "Meta description length needs attention", "low", "Keep the description useful and concise.", f"{len(description)} characters"))

    if parser.h1_count == 0:
        findings.append(_finding("h1_missing", "Homepage H1 is missing", "medium", "Use one clear primary heading that describes the page."))
    elif parser.h1_count > 1:
        findings.append(_finding("h1_multiple", "Homepage has multiple H1 headings", "low", "Review heading hierarchy and keep one clear primary page heading.", f"{parser.h1_count} H1 elements"))

    if not parser.canonical:
        findings.append(_finding("canonical_missing", "Canonical URL is missing", "medium", "Add a self-referencing canonical to reduce duplicate URL ambiguity."))
    else:
        canonical_url = urljoin(final_url, parser.canonical)
        if urlparse(canonical_url).hostname != urlparse(final_url).hostname:
            findings.append(_finding("canonical_external", "Canonical points to another host", "high", "Confirm that the homepage should consolidate indexing signals elsewhere.", canonical_url))

    robots_directives = parser.meta.get("robots", "").lower()
    if "noindex" in robots_directives:
        findings.append(_finding("noindex", "Homepage is marked noindex", "critical", "Remove the noindex directive when the page should appear in search.", robots_directives))

    if "viewport" not in parser.meta:
        findings.append(_finding("viewport_missing", "Mobile viewport metadata is missing", "low", "Add a responsive viewport meta tag."))
    if not parser.html_lang:
        findings.append(_finding("lang_missing", "Document language is not declared", "low", "Set the html lang attribute for accessibility and language targeting."))
    if parser.json_ld_count == 0:
        findings.append(_finding("structured_data_missing", "No JSON-LD structured data detected", "low", "Add valid organization, website, product, or other relevant schema where appropriate."))
    if "og:title" not in parser.meta:
        findings.append(_finding("og_title_missing", "Open Graph title is missing", "low", "Add Open Graph metadata for stronger link previews."))

    if robots_status is None or robots_status >= 400:
        findings.append(_finding("robots_txt_missing", "robots.txt was not found", "low", "Publish a valid robots.txt file and reference the sitemap.", str(robots_status or "unreachable")))
    if sitemap_status is None or sitemap_status >= 400:
        findings.append(_finding("sitemap_missing", "XML sitemap was not found", "medium", "Publish a sitemap.xml so search engines can discover canonical URLs.", str(sitemap_status or "unreachable")))

    if response_time_ms > 3000:
        findings.append(_finding("slow_response", "Homepage response is slow", "medium", "Reduce server response time before rendering work begins.", f"{response_time_ms} ms"))
    elif response_time_ms > 1500:
        findings.append(_finding("response_time", "Homepage response could be faster", "low", "Review origin latency, caching, and middleware overhead.", f"{response_time_ms} ms"))

    weights = {"critical": 25, "high": 15, "medium": 8, "low": 3}
    score = max(0, 100 - sum(weights.get(item["severity"], 0) for item in findings))
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda item: severity_order.get(item["severity"], 9))

    counts = {level: sum(1 for item in findings if item["severity"] == level) for level in weights}
    summary = {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status_code,
        "response_time_ms": response_time_ms,
        "title": title or None,
        "title_length": len(title),
        "description_length": len(description),
        "h1_count": parser.h1_count,
        "canonical": parser.canonical,
        "robots_status": robots_status,
        "sitemap_status": sitemap_status,
        "structured_data_blocks": parser.json_ld_count,
        "issues": counts,
        "checks_run": 14,
    }
    return score, summary, findings


async def execute_free_audit(audit_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        audit = await db.get(FreeAuditRequest, audit_id)
        if not audit or audit.status not in {"queued", "failed"}:
            return
        audit.status = "running"
        audit.started_at = datetime.now(timezone.utc)
        audit.error_code = None
        audit.error_message = None
        await db.commit()

        try:
            final_url, status_code, headers, body, elapsed_ms = await _fetch_html(audit.normalized_url)
            origin = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
            robots_status, sitemap_status = await asyncio.gather(
                _probe(urljoin(origin, "/robots.txt")),
                _probe(urljoin(origin, "/sitemap.xml")),
            )
            score, summary, findings = build_report(
                requested_url=audit.normalized_url,
                final_url=final_url,
                status_code=status_code,
                headers=headers,
                body=body,
                response_time_ms=elapsed_ms,
                robots_status=robots_status,
                sitemap_status=sitemap_status,
            )
            audit.score = score
            audit.summary = summary
            audit.findings = findings
            audit.status = "completed"
            audit.completed_at = datetime.now(timezone.utc)
        except FreeAuditServiceError as exc:
            audit.status = "failed"
            audit.error_code = "blocked_or_unreachable" if exc.status_code == 422 else "audit_failed"
            audit.error_message = str(exc)[:500]
            audit.completed_at = datetime.now(timezone.utc)
        except httpx.TimeoutException:
            audit.status = "failed"
            audit.error_code = "timeout"
            audit.error_message = "Website request timed out"
            audit.completed_at = datetime.now(timezone.utc)
        except httpx.HTTPError as exc:
            audit.status = "failed"
            audit.error_code = "network_error"
            audit.error_message = type(exc).__name__
            audit.completed_at = datetime.now(timezone.utc)
        except Exception as exc:  # pragma: no cover - defensive background boundary
            audit.status = "failed"
            audit.error_code = "internal_error"
            audit.error_message = type(exc).__name__
            audit.completed_at = datetime.now(timezone.utc)
        await db.commit()
