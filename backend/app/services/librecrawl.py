"""LibreCrawl MCP client — wraps the LibreCrawl MCP server's REST API for use as a LangGraph tool."""
import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# LibreCrawl MCP communicates via its underlying LibreCrawl Flask app on LIBRECRAWL_PORT (default 5080).
# The MCP layer adds report generation; we talk to the Flask API directly for crawl operations
# and to the MCP HTTP endpoint for tool calls.

TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)

# MCP Streamable HTTP requires these headers
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _base_url() -> str:
    settings = get_settings()
    return f"http://{settings.librecrawl_host}:{settings.librecrawl_port}"


def _mcp_url() -> str:
    settings = get_settings()
    return f"http://{settings.librecrawl_host}:{settings.librecrawl_mcp_port}/mcp"


def _parse_sse_response(text: str) -> dict[str, Any]:
    """Parse SSE response from MCP streamable HTTP transport.
    Format: 'event: message\\ndata: {...json...}\\n\\n'"""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    # Fallback: try parsing as plain JSON
    return json.loads(text)


async def _call_mcp_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a LibreCrawl MCP tool via the HTTP transport (JSON-RPC over streamable HTTP).

    The MCP streamable HTTP protocol requires:
    1. An initialize handshake to get a session ID
    2. Tool calls with the session ID in Mcp-Session-Id header
    """
    mcp_url = _mcp_url()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Step 1: Initialize session
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "serpstrategist-agent", "version": "0.1.0"},
            },
        }
        init_resp = await client.post(mcp_url, headers=MCP_HEADERS, json=init_payload)
        init_resp.raise_for_status()

        # Extract session ID from response header
        session_id = init_resp.headers.get("mcp-session-id", "")
        if not session_id:
            raise LibreCrawlError("MCP server did not return a session ID")

        # Step 2: Send initialized notification
        initialized_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        session_headers = {**MCP_HEADERS, "Mcp-Session-Id": session_id}
        await client.post(mcp_url, headers=session_headers, json=initialized_payload)

        # Step 3: Call the tool
        tool_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
        resp = await client.post(mcp_url, headers=session_headers, json=tool_payload)
        resp.raise_for_status()

        # Parse SSE response
        data = _parse_sse_response(resp.text)
        if "error" in data:
            raise LibreCrawlError(f"MCP error: {data['error']}")
        return data.get("result", {})


class LibreCrawlError(Exception):
    pass


# ---------------------------------------------------------------------------
# High-level tool functions exposed to the agent graph
# ---------------------------------------------------------------------------


async def site_check(domain: str) -> dict[str, Any]:
    """Quick technical health check — robots.txt, sitemap, HTTPS, www redirect.
    No crawl needed. Used in the observe node for fast site-level signals."""
    try:
        url = f"https://{domain}"
        result = await _call_mcp_tool("librecrawl_site_check", {"url": url})
        logger.info(f"LibreCrawl site_check completed for {domain}")
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl site_check failed for {domain}: {e}")
        return {"error": str(e)}


async def start_audit(domain: str, max_pages: int = 500) -> dict[str, Any]:
    """Trigger a full LibreCrawl audit (crawl + 37 checks + report).
    Returns crawl metadata including crawl_id and report_path."""
    try:
        url = f"https://{domain}"
        result = await _call_mcp_tool("librecrawl_audit", {"url": url, "max_pages": max_pages})
        logger.info(f"LibreCrawl audit started for {domain}")
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl audit failed for {domain}: {e}")
        return {"error": str(e)}


async def get_crawl_status(crawl_id: int | str) -> dict[str, Any]:
    """Poll crawl progress."""
    try:
        result = await _call_mcp_tool("librecrawl_get_status", {"crawl_id": str(crawl_id)})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl get_status failed: {e}")
        return {"error": str(e)}


async def pagespeed(url: str) -> dict[str, Any]:
    """Core Web Vitals for a single URL via Google PageSpeed Insights."""
    try:
        result = await _call_mcp_tool("librecrawl_pagespeed", {"url": url})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl pagespeed failed for {url}: {e}")
        return {"error": str(e)}


async def pagespeed_audit(urls: list[str]) -> dict[str, Any]:
    """Batch Core Web Vitals for multiple URLs, ranked worst-first."""
    try:
        result = await _call_mcp_tool("librecrawl_pagespeed_audit", {"urls": urls})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl pagespeed_audit failed: {e}")
        return {"error": str(e)}


async def schema_check(url: str) -> dict[str, Any]:
    """Extract JSON-LD/Schema.org from a page and map to rich results."""
    try:
        result = await _call_mcp_tool("librecrawl_schema_check", {"url": url})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl schema_check failed for {url}: {e}")
        return {"error": str(e)}


async def schema_audit(urls: list[str]) -> dict[str, Any]:
    """Schema.org coverage across multiple URLs."""
    try:
        result = await _call_mcp_tool("librecrawl_schema_audit", {"urls": urls})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl schema_audit failed: {e}")
        return {"error": str(e)}


async def internal_links_analysis(domain: str) -> dict[str, Any]:
    """Internal authority map — top linked pages, orphans, dead ends, anchor text."""
    try:
        url = f"https://{domain}"
        result = await _call_mcp_tool("librecrawl_internal_links_analysis", {"url": url})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl internal_links_analysis failed for {domain}: {e}")
        return {"error": str(e)}


async def export_results(crawl_id: int | str) -> dict[str, Any]:
    """Raw JSON export of all crawl data for a given crawl_id."""
    try:
        result = await _call_mcp_tool("librecrawl_export_results", {"crawl_id": str(crawl_id)})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl export_results failed: {e}")
        return {"error": str(e)}


async def list_crawls() -> dict[str, Any]:
    """List all saved crawls with their status and metadata."""
    try:
        result = await _call_mcp_tool("librecrawl_list_crawls", {})
        return result
    except Exception as e:
        logger.warning(f"LibreCrawl list_crawls failed: {e}")
        return {"error": str(e)}


async def is_available() -> bool:
    """Check if the LibreCrawl MCP server is reachable."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{_base_url()}/")
            return resp.status_code == 200
    except Exception:
        return False


async def crawl_and_sync_pages(domain: str, site_id: "uuid.UUID", max_pages: int = 500) -> dict[str, Any]:
    """Run a full LibreCrawl crawl and sync discovered pages into our DB.
    
    This replaces the basic HTTP crawler with LibreCrawl's Playwright-based crawler
    which renders JS and discovers more URLs.
    
    Returns: {"pages_synced": int, "crawl_id": int} or {"error": str}
    """
    import uuid as uuid_mod
    import json as json_mod
    from datetime import datetime, timezone
    from urllib.parse import urlparse
    from sqlalchemy import select, delete as sa_delete
    from app.database import async_session_factory
    from app.models.page import Page

    try:
        # Step 1: Start crawl via MCP audit tool (crawls + analyzes)
        url = f"https://{domain}"
        audit_result = await _call_mcp_tool("librecrawl_audit", {"url": url, "max_pages": max_pages})

        if not audit_result or "error" in audit_result:
            return {"error": f"LibreCrawl audit failed: {audit_result}"}

        # Step 2: Find the latest completed crawl for this domain
        crawls_result = await _call_mcp_tool("librecrawl_list_crawls", {})
        crawls_content = crawls_result.get("content", [])
        crawl_id = None
        if crawls_content:
            for item in crawls_content:
                if "text" in item:
                    try:
                        crawls_data = json_mod.loads(item["text"])
                    except (json_mod.JSONDecodeError, TypeError):
                        continue
                    crawls_list = crawls_data.get("crawls", [])
                    # Find the most recent completed crawl for this domain (list is sorted newest first)
                    for c in crawls_list:
                        if c.get("base_domain") == domain and c.get("status") == "completed":
                            crawl_id = c["id"]
                            break
                    break

        if not crawl_id:
            return {"error": "Could not find completed crawl for domain"}

        # Step 3: Export full crawl data
        export_result = await _call_mcp_tool("librecrawl_export_results", {"crawl_id": str(crawl_id)})
        export_content = export_result.get("content", [])
        pages_data = []
        if export_content:
            for item in export_content:
                if "text" in item:
                    try:
                        export_parsed = json_mod.loads(item["text"])
                        pages_data = export_parsed.get("pages", [])
                    except (json_mod.JSONDecodeError, TypeError):
                        logger.warning(f"Failed to parse export for crawl {crawl_id}")
                        continue
                    break

        if not pages_data:
            # If latest crawl export is empty, try the previous one
            for item in crawls_content:
                if "text" in item:
                    try:
                        crawls_data = json_mod.loads(item["text"])
                    except (json_mod.JSONDecodeError, TypeError):
                        continue
                    crawls_list = crawls_data.get("crawls", [])
                    for c in crawls_list:
                        if c.get("base_domain") == domain and c.get("status") == "completed" and c["id"] != crawl_id:
                            alt_export = await _call_mcp_tool("librecrawl_export_results", {"crawl_id": str(c["id"])})
                            alt_content = alt_export.get("content", [])
                            for ac in alt_content:
                                if "text" in ac:
                                    try:
                                        alt_parsed = json_mod.loads(ac["text"])
                                        pages_data = alt_parsed.get("pages", [])
                                    except (json_mod.JSONDecodeError, TypeError):
                                        continue
                                    break
                            if pages_data:
                                crawl_id = c["id"]
                                break
                    break

        if not pages_data:
            return {"error": "No pages in LibreCrawl export"}

        # Step 4: Sync pages into our database
        async with async_session_factory() as db:
            # Delete existing pages for this site (full replacement)
            await db.execute(sa_delete(Page).where(Page.site_id == site_id))

            def _int_or_none(val):
                if val is None or val == "":
                    return None
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    return None

            seen_paths: set[str] = set()
            pages_synced = 0
            for p in pages_data:
                page_url = p.get("url", "")
                if not page_url:
                    continue

                # Convert full URL to relative path
                parsed = urlparse(page_url)
                path = parsed.path or "/"
                if parsed.query:
                    path += f"?{parsed.query}"

                # Skip duplicates (same path from different URL variants)
                if path in seen_paths:
                    continue
                seen_paths.add(path)

                # Build meta JSONB with rich data from LibreCrawl export
                page_meta = {}
                for key in ("og_tags", "json_ld", "analytics", "twitter_tags",
                            "images", "linked_from", "h2", "h3", "robots",
                            "lang", "charset", "viewport", "hreflang", "redirects"):
                    val = p.get(key)
                    if val:
                        page_meta[key] = val
                # Store link counts as integers
                int_links = p.get("internal_links")
                ext_links = p.get("external_links")
                if int_links is not None:
                    page_meta["internal_links_count"] = int(int_links) if isinstance(int_links, (int, float)) else len(int_links) if isinstance(int_links, list) else 0
                if ext_links is not None:
                    page_meta["external_links_count"] = int(ext_links) if isinstance(ext_links, (int, float)) else len(ext_links) if isinstance(ext_links, list) else 0
                # Image stats
                images_data = p.get("images", [])
                if isinstance(images_data, list):
                    page_meta["images_count"] = len(images_data)
                    page_meta["images_without_alt"] = sum(
                        1 for img in images_data if isinstance(img, dict) and "alt" not in img
                    )
                # Size
                size_val = p.get("size")
                if size_val:
                    page_meta["size_bytes"] = _int_or_none(size_val)

                page = Page(
                    site_id=site_id,
                    path=path,
                    title=p.get("title") or None,
                    meta_description=p.get("meta_description") or None,
                    h1=p.get("h1") or None,
                    status_code=_int_or_none(p.get("status_code")),
                    word_count=_int_or_none(p.get("word_count")),
                    response_time_ms=_int_or_none(p.get("response_time_ms")),
                    canonical_url=p.get("canonical_url") or None,
                    meta=page_meta if page_meta else None,
                    last_crawled_at=datetime.now(timezone.utc),
                )
                db.add(page)
                pages_synced += 1

            await db.commit()

        logger.info(f"LibreCrawl sync: {pages_synced} pages imported for {domain} (crawl #{crawl_id})")
        return {"pages_synced": pages_synced, "crawl_id": crawl_id}

    except Exception as e:
        logger.warning(f"LibreCrawl crawl_and_sync_pages failed for {domain}: {e}")
        return {"error": str(e)}


async def sync_issues_from_export(site_id: "uuid.UUID", crawl_id: int | None = None) -> dict[str, Any]:
    """Analyze the LibreCrawl export data and create per-page issues in our DB.
    
    This replicates the 35+ checks LibreCrawl runs (title length, duplicates,
    missing meta, thin content, images without alt, orphan pages, etc.)
    
    Returns: {"issues_created": int} or {"error": str}
    """
    import uuid as uuid_mod
    import json as json_mod
    from collections import Counter
    from urllib.parse import urlparse
    from sqlalchemy import delete as sa_delete
    from app.database import async_session_factory
    from app.models.issue import Issue

    try:
        # Get the latest crawl if no crawl_id specified
        if not crawl_id:
            crawls_result = await _call_mcp_tool("librecrawl_list_crawls", {})
            crawls_content = crawls_result.get("content", [])
            for item in crawls_content:
                if "text" in item:
                    try:
                        crawls_data = json_mod.loads(item["text"])
                    except (json_mod.JSONDecodeError, TypeError):
                        continue
                    for c in crawls_data.get("crawls", []):
                        if c.get("status") == "completed":
                            crawl_id = c["id"]
                            break
                    break

        if not crawl_id:
            return {"error": "No completed crawl found"}

        # Export crawl data
        export_result = await _call_mcp_tool("librecrawl_export_results", {"crawl_id": str(crawl_id)})
        export_content = export_result.get("content", [])
        pages_data = []
        for item in export_content:
            if "text" in item:
                try:
                    export_parsed = json_mod.loads(item["text"])
                    pages_data = export_parsed.get("pages", [])
                except (json_mod.JSONDecodeError, TypeError):
                    continue
                break

        if not pages_data:
            return {"error": "No pages in export"}

        # Run all checks
        issues: list[dict] = []

        # Collect titles and metas for duplicate detection
        titles: dict[str, list[str]] = {}
        metas: dict[str, list[str]] = {}
        
        for p in pages_data:
            url = p.get("url", "")
            title = p.get("title", "")
            meta = p.get("meta_description", "")
            h1 = p.get("h1", "")
            word_count = p.get("word_count", 0) or 0
            canonical = p.get("canonical_url", "")
            status_code = p.get("status_code", 200)
            images = p.get("images", [])
            linked_from = p.get("linked_from", [])
            response_time = p.get("response_time_ms", "")
            
            # Parse path for affected_url
            parsed_url = urlparse(url)
            path = parsed_url.path or "/"

            # --- Title checks ---
            if not title:
                issues.append({
                    "category": "seo", "severity": "critical",
                    "title": "Missing page title",
                    "description": f"The page at {path} has no <title> tag. This is critical for SEO as the title tag is one of the most important ranking signals.",
                    "recommendation": "Add a unique, descriptive title tag (50-60 characters) that includes your target keyword.",
                    "affected_url": path,
                })
            elif len(title) > 60:
                issues.append({
                    "category": "seo", "severity": "medium",
                    "title": "Title too long",
                    "description": f"Title is {len(title)} characters (max 60). It will be truncated in search results.",
                    "recommendation": f"Shorten the title to under 60 characters. Current: \"{title[:80]}...\"",
                    "affected_url": path,
                })
            elif len(title) < 30 and title:
                issues.append({
                    "category": "seo", "severity": "medium",
                    "title": "Title too short",
                    "description": f"Title is only {len(title)} characters. Short titles miss keyword opportunities.",
                    "recommendation": "Expand the title to 50-60 characters with relevant keywords.",
                    "affected_url": path,
                })

            # Track for duplicate detection
            if title:
                titles.setdefault(title, []).append(path)

            # --- Meta description checks ---
            if not meta:
                issues.append({
                    "category": "seo", "severity": "high",
                    "title": "Missing meta description",
                    "description": f"The page at {path} has no meta description. Google may generate one from page content.",
                    "recommendation": "Add a compelling meta description (120-160 characters) with a call to action.",
                    "affected_url": path,
                })
            elif len(meta) > 160:
                issues.append({
                    "category": "seo", "severity": "medium",
                    "title": "Meta description too long",
                    "description": f"Meta description is {len(meta)} characters (max 160). It will be truncated in SERPs.",
                    "recommendation": "Shorten to under 160 characters while keeping the key message.",
                    "affected_url": path,
                })
            elif len(meta) < 70 and meta:
                issues.append({
                    "category": "seo", "severity": "medium",
                    "title": "Meta description too short",
                    "description": f"Meta description is only {len(meta)} characters. You're missing SERP real estate.",
                    "recommendation": "Expand to 120-160 characters with compelling copy and a CTA.",
                    "affected_url": path,
                })

            if meta:
                metas.setdefault(meta, []).append(path)

            # --- H1 checks ---
            if not h1:
                issues.append({
                    "category": "seo", "severity": "high",
                    "title": "Missing H1 heading",
                    "description": f"The page at {path} has no H1 tag. The H1 signals the main topic to search engines.",
                    "recommendation": "Add a single, descriptive H1 that includes the primary keyword.",
                    "affected_url": path,
                })

            # --- Content checks ---
            if isinstance(word_count, int) and word_count < 300 and word_count > 0:
                issues.append({
                    "category": "content", "severity": "medium",
                    "title": "Thin content",
                    "description": f"Page at {path} has only {word_count} words. Pages with <300 words may struggle to rank.",
                    "recommendation": "Add more substantive, valuable content to reach at least 300+ words.",
                    "affected_url": path,
                })

            # --- Canonical checks ---
            if canonical and canonical != url:
                # Non-self canonical
                canonical_parsed = urlparse(canonical)
                if canonical_parsed.path != parsed_url.path:
                    issues.append({
                        "category": "technical", "severity": "medium",
                        "title": "Non-self canonical",
                        "description": f"Page {path} has canonical pointing to {canonical_parsed.path}. This tells Google to ignore this page.",
                        "recommendation": "Verify this is intentional. If the page should be indexed, set canonical to itself.",
                        "affected_url": path,
                    })

            # --- Image alt text checks ---
            if images:
                missing_alt = sum(1 for img in images if isinstance(img, dict) and not img.get("alt"))
                if missing_alt > 0:
                    issues.append({
                        "category": "accessibility", "severity": "medium",
                        "title": "Images without alt text",
                        "description": f"{missing_alt} of {len(images)} images on {path} lack alt attributes.",
                        "recommendation": "Add descriptive alt text to all informational images for accessibility and SEO.",
                        "affected_url": path,
                    })

            # --- Orphan page checks ---
            if not linked_from:
                issues.append({
                    "category": "structure", "severity": "medium",
                    "title": "Orphan page",
                    "description": f"Page {path} has zero internal links pointing to it. Search engines may not discover it.",
                    "recommendation": "Add internal links from relevant pages to help search engines and users find this content.",
                    "affected_url": path,
                })

            # --- Performance checks ---
            if response_time and response_time != "":
                try:
                    rt_ms = int(response_time)
                    if rt_ms > 3000:
                        issues.append({
                            "category": "performance", "severity": "high",
                            "title": "Slow page response",
                            "description": f"Page {path} took {rt_ms}ms to respond (threshold: 3000ms).",
                            "recommendation": "Optimize server response time. Check database queries, caching, and server resources.",
                            "affected_url": path,
                        })
                except (ValueError, TypeError):
                    pass

            # --- Status code checks ---
            if isinstance(status_code, int):
                if 400 <= status_code < 500:
                    issues.append({
                        "category": "technical", "severity": "critical",
                        "title": f"Client error ({status_code})",
                        "description": f"Page {path} returns HTTP {status_code}. This is a broken page.",
                        "recommendation": "Fix the page or remove links pointing to it. Set up proper redirects if the content moved.",
                        "affected_url": path,
                    })
                elif 500 <= status_code < 600:
                    issues.append({
                        "category": "technical", "severity": "critical",
                        "title": f"Server error ({status_code})",
                        "description": f"Page {path} returns HTTP {status_code}. This indicates a server-side problem.",
                        "recommendation": "Check server logs and fix the underlying error.",
                        "affected_url": path,
                    })

            # --- URL checks ---
            if any(c.isupper() for c in parsed_url.path):
                issues.append({
                    "category": "technical", "severity": "low",
                    "title": "Uppercase in URL",
                    "description": f"URL {path} contains uppercase characters. This can cause duplicate content issues.",
                    "recommendation": "Use lowercase URLs and redirect uppercase variants with 301.",
                    "affected_url": path,
                })

        # --- Duplicate title issues ---
        for title_text, paths in titles.items():
            if len(paths) > 1:
                paths_str = ", ".join(paths[:5])
                issues.append({
                    "category": "seo", "severity": "high",
                    "title": "Duplicate title tag",
                    "description": f"The title \"{title_text[:80]}\" is shared by {len(paths)} pages: {paths_str}. Each page should have a unique title.",
                    "recommendation": "Write unique, descriptive titles for each page that reflect its specific content.",
                    "affected_url": paths[0],
                })

        # --- Duplicate meta description issues ---
        for meta_text, paths in metas.items():
            if len(paths) > 1:
                paths_str = ", ".join(paths[:5])
                issues.append({
                    "category": "seo", "severity": "high",
                    "title": "Duplicate meta description",
                    "description": f"The meta description is shared by {len(paths)} pages: {paths_str}. Each page should have unique copy.",
                    "recommendation": "Write unique meta descriptions that accurately summarize each page's content.",
                    "affected_url": paths[0],
                })

        # Save to DB — replace existing issues for this site
        async with async_session_factory() as db:
            await db.execute(sa_delete(Issue).where(Issue.site_id == site_id))

            for issue_data in issues:
                db.add(Issue(
                    site_id=site_id,
                    category=issue_data["category"],
                    severity=issue_data["severity"],
                    title=issue_data["title"],
                    description=issue_data["description"],
                    recommendation=issue_data.get("recommendation"),
                    affected_url=issue_data.get("affected_url"),
                ))

            await db.commit()

        logger.info(f"LibreCrawl issue sync: {len(issues)} issues created for site (crawl #{crawl_id})")
        return {"issues_created": len(issues)}

    except Exception as e:
        logger.warning(f"LibreCrawl sync_issues_from_export failed: {e}")
        return {"error": str(e)}
