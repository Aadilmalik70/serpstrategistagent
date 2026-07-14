"""Deterministic crawl → technical findings → governed actions graph."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.page import Page
from app.models.site import Site
from app.services.health_score import calculate_health_score
from app.services.technical_finding_service import run_technical_finding_pipeline


logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    site_id: str
    run_id: str
    pages: list[dict[str, Any]]
    issues_created: int
    actions_created: int
    reconciliation: dict[str, Any]
    error: str | None
    health_score: dict[str, Any] | None


async def observe_node(state: AgentState) -> AgentState:
    site_id = uuid.UUID(state["site_id"])
    async with async_session_factory() as db:
        pages = list((await db.execute(
            select(Page).where(Page.site_id == site_id).order_by(Page.path)
        )).scalars().all())
        state["pages"] = [
            {
                "id": str(page.id),
                "path": page.path,
                "status_code": page.status_code,
                "content_hash": page.content_hash,
                "last_crawled_at": page.last_crawled_at.isoformat() if page.last_crawled_at else None,
            }
            for page in pages
        ]
    return state


async def analyze_node(state: AgentState) -> AgentState:
    site_id = uuid.UUID(state["site_id"])
    run_id = uuid.UUID(state["run_id"])
    if not state["pages"]:
        state["error"] = "No pages found to analyze. Run a crawl first."
        return state

    async with async_session_factory() as db:
        site = await db.get(Site, site_id)
        if not site:
            state["error"] = "Site no longer exists."
            return state
        result = await run_technical_finding_pipeline(db, site=site, run_id=run_id)
        state["reconciliation"] = result
        state["issues_created"] = int(result["active"])
        state["actions_created"] = int(result["actions_created"])
    return state


async def report_node(state: AgentState) -> AgentState:
    site_id = uuid.UUID(state["site_id"])
    run_id = uuid.UUID(state["run_id"])
    async with async_session_factory() as db:
        agent_run = await db.get(AgentRun, run_id)
        if not agent_run:
            return state
        if state.get("error"):
            agent_run.status = "failed"
            agent_run.error = state["error"]
            agent_run.summary = state["error"]
            agent_run.pages_analyzed = 0
            agent_run.issues_found = 0
        else:
            health = await calculate_health_score(db, site_id)
            state["health_score"] = health
            reconciliation = state.get("reconciliation") or {}
            agent_run.status = "completed"
            agent_run.pages_analyzed = len(state["pages"])
            agent_run.issues_found = state["issues_created"]
            agent_run.meta = {
                **(agent_run.meta or {}),
                "phase": "completed",
                "technical_findings": {
                    key: reconciliation.get(key, 0)
                    for key in ("created", "updated", "regressed", "resolved", "active", "actions_created")
                },
            }
            agent_run.summary = (
                f"Analyzed {len(state['pages'])} pages. "
                f"{state['issues_created']} active technical findings; "
                f"{state['actions_created']} governed actions created. "
                f"Health: {health['score']}/100 ({health['grade']})."
            )
        agent_run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    return state


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("observe", observe_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "observe")
    graph.add_edge("observe", "analyze")
    graph.add_edge("analyze", "report")
    graph.add_edge("report", END)
    return graph.compile()


agent_graph = build_agent_graph()


async def run_agent_graph(site_id: uuid.UUID, run_id: uuid.UUID) -> None:
    try:
        await agent_graph.ainvoke({
            "site_id": str(site_id),
            "run_id": str(run_id),
            "pages": [],
            "issues_created": 0,
            "actions_created": 0,
            "reconciliation": {},
            "error": None,
            "health_score": None,
        })
    except Exception as exc:
        logger.exception("Agent graph failed for site %s", site_id)
        async with async_session_factory() as db:
            agent_run = await db.get(AgentRun, run_id)
            if agent_run:
                agent_run.status = "failed"
                agent_run.error = str(exc)[:2000]
                agent_run.summary = str(exc)[:2000]
                agent_run.completed_at = datetime.now(timezone.utc)
                await db.commit()
