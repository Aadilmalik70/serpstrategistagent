"""LangGraph-based SEO analysis agent with observe → analyze → report nodes."""
import uuid
import logging
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from app.database import async_session_factory
from app.config import get_settings
from app.models.site import Site
from app.models.page import Page
from app.models.issue import Issue
from app.models.agent_run import AgentRun
from app.services.agent import PAGE_CHECKS, _check_duplicate_title
from app.services.llm_analyzer import analyze_site_with_llm
from app.services.health_score import calculate_health_score
from app.services import librecrawl

from sqlalchemy import select, delete

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    site_id: str
    run_id: str
    pages: list[dict]
    issues_created: int
    error: str | None
    health_score: dict | None
    # LibreCrawl technical audit data
    librecrawl_site_check: dict | None
    librecrawl_audit: dict | None


async def observe_node(state: AgentState) -> AgentState:
    """Observe node: Load crawled pages from DB + run LibreCrawl site-level checks."""
    site_id = uuid.UUID(state["site_id"])
    settings = get_settings()

    async with async_session_factory() as db:
        # Load site domain for LibreCrawl calls
        site = await db.get(Site, site_id)
        domain = site.domain if site else ""

        result = await db.execute(
            select(Page).where(Page.site_id == site_id).order_by(Page.path)
        )
        pages = list(result.scalars().all())

        state["pages"] = [
            {
                "id": str(p.id),
                "path": p.path,
                "title": p.title,
                "meta_description": p.meta_description,
                "h1": p.h1,
                "word_count": p.word_count,
                "status_code": p.status_code,
                "response_time_ms": p.response_time_ms,
            }
            for p in pages
        ]

    # LibreCrawl: quick site-level health (robots.txt, sitemap, HTTPS, www)
    if settings.librecrawl_enabled and domain:
        site_check_result = await librecrawl.site_check(domain)
        state["librecrawl_site_check"] = site_check_result
        if "error" not in site_check_result:
            logger.info(f"LibreCrawl site_check: {domain} — signals collected")
    else:
        state["librecrawl_site_check"] = None

    return state


async def analyze_node(state: AgentState) -> AgentState:
    """Analyze node: Run rule-based checks + LLM analysis + LibreCrawl audit, create issues."""
    site_id = uuid.UUID(state["site_id"])
    run_id = uuid.UUID(state["run_id"])
    settings = get_settings()

    async with async_session_factory() as db:
        # Clear ALL previous issues for this site (full re-analysis replaces old data)
        await db.execute(
            delete(Issue).where(Issue.site_id == site_id)
        )
        await db.commit()

        # Load pages (need ORM objects for rule checks)
        result = await db.execute(
            select(Page).where(Page.site_id == site_id).order_by(Page.path)
        )
        pages = list(result.scalars().all())

        if not pages:
            state["error"] = "No pages found to analyze. Run a crawl first."
            return state

        issues_created = 0

        # Rule-based checks
        for page in pages:
            for check_fn in PAGE_CHECKS:
                issue_data = check_fn(page)
                if issue_data:
                    issue = Issue(
                        site_id=site_id,
                        page_id=page.id,
                        agent_run_id=run_id,
                        affected_url=page.path,
                        **issue_data,
                    )
                    db.add(issue)
                    issues_created += 1

        # Cross-page checks
        for issue_data in _check_duplicate_title(pages):
            issue = Issue(
                site_id=site_id,
                agent_run_id=run_id,
                **issue_data,
            )
            db.add(issue)
            issues_created += 1

        # --- LibreCrawl technical SEO audit ---
        site = await db.get(Site, site_id)
        domain = site.domain if site else ""

        if settings.librecrawl_enabled and domain:
            audit_result = await librecrawl.start_audit(domain, max_pages=min(len(pages) * 2, 500))
            state["librecrawl_audit"] = audit_result

            # Convert LibreCrawl site_check signals into issues
            site_check = state.get("librecrawl_site_check") or {}
            issues_created += _create_issues_from_site_check(
                db, site_id, run_id, site_check
            )

            # Convert LibreCrawl audit findings into issues
            if "error" not in audit_result:
                issues_created += _create_issues_from_audit(
                    db, site_id, run_id, audit_result
                )
        else:
            state["librecrawl_audit"] = None

        # LLM-powered analysis
        site_context = {
            "domain": domain,
            "site_name": site.name if site else "",
            "total_pages": len(pages),
            "librecrawl_site_check": state.get("librecrawl_site_check"),
        }
        pages_data = [
            {
                "path": p.path,
                "title": p.title,
                "meta_description": p.meta_description,
                "h1": p.h1,
                "word_count": p.word_count,
                "status_code": p.status_code,
                "response_time_ms": p.response_time_ms,
                "page_id": p.id,
            }
            for p in pages
        ]

        llm_results = await analyze_site_with_llm(pages_data, site_context)
        for page_data, insights in llm_results:
            for insight in insights:
                issue = Issue(
                    site_id=site_id,
                    page_id=page_data.get("page_id"),
                    agent_run_id=run_id,
                    category=insight.category,
                    severity=insight.severity,
                    title=insight.title,
                    description=insight.description,
                    recommendation=insight.recommendation,
                    affected_url=page_data.get("path"),
                )
                db.add(issue)
                issues_created += 1

        await db.commit()
        state["issues_created"] = issues_created

    return state


async def report_node(state: AgentState) -> AgentState:
    """Report node: Finalize run record with results and health score."""
    site_id = uuid.UUID(state["site_id"])
    run_id = uuid.UUID(state["run_id"])

    async with async_session_factory() as db:
        agent_run = await db.get(AgentRun, run_id)
        if not agent_run:
            return state

        if state.get("error"):
            agent_run.status = "completed"
            agent_run.summary = state["error"]
            agent_run.pages_analyzed = 0
            agent_run.issues_found = 0
        else:
            agent_run.status = "completed"
            agent_run.pages_analyzed = len(state["pages"])
            agent_run.issues_found = state["issues_created"]

            # Calculate health score
            health = await calculate_health_score(db, site_id)
            state["health_score"] = health

            librecrawl_note = ""
            if state.get("librecrawl_audit") and "error" not in state["librecrawl_audit"]:
                librecrawl_note = " [+LibreCrawl audit]"

            agent_run.summary = (
                f"Analyzed {len(state['pages'])} pages. "
                f"Found {state['issues_created']} issues. "
                f"Health: {health['score']}/100 ({health['grade']})"
                f"{librecrawl_note}"
            )

        agent_run.completed_at = datetime.now(timezone.utc)
        await db.commit()

    return state


# ---------------------------------------------------------------------------
# LibreCrawl → Issue converters
# ---------------------------------------------------------------------------

def _create_issues_from_site_check(
    db, site_id: uuid.UUID, run_id: uuid.UUID, site_check: dict
) -> int:
    """Convert LibreCrawl site_check results into Issue records.
    Returns number of issues created."""
    if not site_check or "error" in site_check:
        return 0

    issues_created = 0
    content = site_check.get("content", [{}])
    # MCP tool results come as content[].text (JSON string)
    data = _parse_mcp_content(content)
    if not data:
        return 0

    # Check robots.txt
    robots = data.get("robots_txt", {})
    if robots.get("status") == "missing":
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="high",
            title="Missing robots.txt",
            description="No robots.txt found. Search engines have no crawl directives.",
            recommendation="Create a robots.txt file with appropriate crawl rules and a Sitemap directive.",
        ))
        issues_created += 1

    # Check sitemap
    sitemap = data.get("sitemap", {})
    if sitemap.get("status") == "missing":
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="high",
            title="Missing sitemap.xml",
            description="No sitemap.xml found. Search engines may miss pages.",
            recommendation="Generate and submit an XML sitemap listing all indexable URLs.",
        ))
        issues_created += 1

    # Check HTTPS
    https_check = data.get("https", {})
    if not https_check.get("redirects_to_https", True):
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="critical",
            title="No HTTPS redirect",
            description="HTTP does not redirect to HTTPS. This hurts rankings and security.",
            recommendation="Configure server to 301 redirect all HTTP traffic to HTTPS.",
        ))
        issues_created += 1

    # Check www canonicalization
    www = data.get("www_canonicalization", {})
    if www.get("issue"):
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="medium",
            title="www/non-www not canonicalized",
            description="Both www and non-www versions resolve without redirecting to one canonical.",
            recommendation="Choose one version (www or non-www) and 301 redirect the other.",
        ))
        issues_created += 1

    return issues_created


def _create_issues_from_audit(
    db, site_id: uuid.UUID, run_id: uuid.UUID, audit_result: dict
) -> int:
    """Convert LibreCrawl full audit findings into Issue records.
    Returns number of issues created."""
    if not audit_result or "error" in audit_result:
        return 0

    content = audit_result.get("content", [{}])
    data = _parse_mcp_content(content)
    if not data:
        return 0

    issues_created = 0

    # Broken links (4xx/5xx)
    broken_links = data.get("broken_links", [])
    for bl in broken_links[:20]:  # Cap to avoid flooding
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="critical",
            title=f"Broken link: {bl.get('url', 'unknown')} ({bl.get('status_code', '?')})",
            description=f"Found on: {bl.get('source_page', 'unknown')}",
            recommendation="Fix or remove the broken link.",
            affected_url=bl.get("source_page"),
        ))
        issues_created += 1

    # Redirect chains
    redirect_chains = data.get("redirect_chains", [])
    for chain in redirect_chains[:10]:
        chain_str = " → ".join(chain.get("chain", []))
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="medium",
            title=f"Redirect chain ({len(chain.get('chain', []))} hops)",
            description=f"Chain: {chain_str}",
            recommendation="Update links to point directly to the final destination URL.",
            affected_url=chain.get("chain", [""])[0] if chain.get("chain") else None,
        ))
        issues_created += 1

    # Orphan pages
    orphan_pages = data.get("orphan_pages", [])
    for orphan in orphan_pages[:15]:
        url = orphan if isinstance(orphan, str) else orphan.get("url", "")
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="structure", severity="medium",
            title=f"Orphan page: {url}",
            description="This page has zero internal links pointing to it. Googlebot may not discover it.",
            recommendation="Add internal links from relevant pages to this URL.",
            affected_url=url,
        ))
        issues_created += 1

    # Canonical issues
    canonical_issues = data.get("canonical_issues", [])
    for ci in canonical_issues[:10]:
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="technical", severity="high",
            title=f"Canonical issue: {ci.get('type', 'unknown')}",
            description=f"URL: {ci.get('url', '')} — {ci.get('detail', '')}",
            recommendation="Fix the canonical tag to point to the correct preferred URL.",
            affected_url=ci.get("url"),
        ))
        issues_created += 1

    # Missing alt text (aggregate)
    images = data.get("images", {})
    missing_alt_count = images.get("missing_alt_count", 0)
    if missing_alt_count > 0:
        db.add(Issue(
            site_id=site_id, agent_run_id=run_id,
            category="accessibility", severity="medium",
            title=f"Missing image alt text ({missing_alt_count} images)",
            description=f"{missing_alt_count} images lack alt attributes across the site.",
            recommendation="Add descriptive alt text to all informational images.",
        ))
        issues_created += 1

    return issues_created


def _parse_mcp_content(content) -> dict | None:
    """Parse MCP tool result content array into a dict."""
    import json
    if not content:
        return None
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and "text" in item:
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, TypeError):
                    return None
            if isinstance(item, dict):
                return item
    return None


# ---------------------------------------------------------------------------


def build_agent_graph():
    """Build the LangGraph state machine for SEO analysis."""
    graph = StateGraph(AgentState)

    graph.add_node("observe", observe_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "observe")
    graph.add_edge("observe", "analyze")
    graph.add_edge("analyze", "report")
    graph.add_edge("report", END)

    return graph.compile()


# Compiled graph (singleton)
agent_graph = build_agent_graph()


async def run_agent_graph(site_id: uuid.UUID, run_id: uuid.UUID):
    """Execute the full agent graph for a site."""
    try:
        initial_state: AgentState = {
            "site_id": str(site_id),
            "run_id": str(run_id),
            "pages": [],
            "issues_created": 0,
            "error": None,
            "health_score": None,
            "librecrawl_site_check": None,
            "librecrawl_audit": None,
        }

        await agent_graph.ainvoke(initial_state)

    except Exception as e:
        logger.error(f"Agent graph failed for site {site_id}: {e}")
        # Mark run as failed
        async with async_session_factory() as db:
            agent_run = await db.get(AgentRun, run_id)
            if agent_run:
                agent_run.status = "failed"
                agent_run.error = str(e)
                agent_run.completed_at = datetime.now(timezone.utc)
                await db.commit()
