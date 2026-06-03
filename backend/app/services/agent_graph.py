"""LangGraph-based SEO analysis agent with observe → analyze → report nodes."""
import uuid
import logging
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from app.database import async_session_factory
from app.models.site import Site
from app.models.page import Page
from app.models.issue import Issue
from app.models.agent_run import AgentRun
from app.services.agent import PAGE_CHECKS, _check_duplicate_title
from app.services.llm_analyzer import analyze_site_with_llm
from app.services.health_score import calculate_health_score

from sqlalchemy import select, delete

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    site_id: str
    run_id: str
    pages: list[dict]
    issues_created: int
    error: str | None
    health_score: dict | None


async def observe_node(state: AgentState) -> AgentState:
    """Observe node: Load crawled pages from DB."""
    site_id = uuid.UUID(state["site_id"])

    async with async_session_factory() as db:
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

    return state


async def analyze_node(state: AgentState) -> AgentState:
    """Analyze node: Run rule-based checks + LLM analysis, create issues."""
    site_id = uuid.UUID(state["site_id"])
    run_id = uuid.UUID(state["run_id"])

    async with async_session_factory() as db:
        # Clear previous open issues
        await db.execute(
            delete(Issue).where(Issue.site_id == site_id, Issue.status == "open")
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

        # LLM-powered analysis
        site = await db.get(Site, site_id)
        site_context = {
            "domain": site.domain if site else "",
            "site_name": site.name if site else "",
            "total_pages": len(pages),
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
            agent_run.summary = (
                f"Analyzed {len(state['pages'])} pages. "
                f"Found {state['issues_created']} issues. "
                f"Health: {health['score']}/100 ({health['grade']})"
            )

        agent_run.completed_at = datetime.now(timezone.utc)
        await db.commit()

    return state


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
