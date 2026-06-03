"""SEO Analysis Agent — Analyzes crawled pages and produces actionable issues."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site import Site
from app.models.page import Page
from app.models.issue import Issue
from app.models.agent_run import AgentRun


# Issue detection rules (no LLM needed for these)
def _check_missing_title(page: Page) -> dict | None:
    if not page.title or page.title.strip() == "":
        return {
            "category": "technical",
            "severity": "critical",
            "title": "Missing page title",
            "description": f"The page at {page.path} has no <title> tag. This is critical for SEO as the title tag is one of the most important ranking signals.",
            "recommendation": "Add a unique, descriptive title tag (50-60 characters) that includes your target keyword.",
        }
    return None


def _check_title_length(page: Page) -> dict | None:
    if page.title and len(page.title) > 60:
        return {
            "category": "technical",
            "severity": "medium",
            "title": "Title tag too long",
            "description": f"The page at {page.path} has a title of {len(page.title)} characters (\"{page.title[:80]}...\"). Google typically displays 50-60 characters.",
            "recommendation": f"Shorten the title to under 60 characters while keeping the primary keyword near the front.",
        }
    if page.title and len(page.title) < 20:
        return {
            "category": "technical",
            "severity": "low",
            "title": "Title tag too short",
            "description": f"The page at {page.path} has a title of only {len(page.title)} characters (\"{page.title}\"). Short titles miss ranking opportunities.",
            "recommendation": "Expand the title to 50-60 characters, incorporating relevant keywords.",
        }
    return None


def _check_missing_meta_description(page: Page) -> dict | None:
    if not page.meta_description or page.meta_description.strip() == "":
        return {
            "category": "technical",
            "severity": "high",
            "title": "Missing meta description",
            "description": f"The page at {page.path} has no meta description. Google will auto-generate one, but a custom description improves CTR.",
            "recommendation": "Write a compelling meta description (150-160 characters) that includes your target keyword and a call to action.",
        }
    return None


def _check_meta_description_length(page: Page) -> dict | None:
    if page.meta_description and len(page.meta_description) > 160:
        return {
            "category": "technical",
            "severity": "low",
            "title": "Meta description too long",
            "description": f"The page at {page.path} has a meta description of {len(page.meta_description)} characters. Google truncates after ~155-160 characters.",
            "recommendation": "Shorten to 150-160 characters while keeping the key value proposition.",
        }
    return None


def _check_missing_h1(page: Page) -> dict | None:
    if page.status_code == 200 and (not page.h1 or page.h1.strip() == ""):
        return {
            "category": "technical",
            "severity": "high",
            "title": "Missing H1 heading",
            "description": f"The page at {page.path} has no H1 tag. The H1 is a strong relevance signal for search engines.",
            "recommendation": "Add a single H1 tag that clearly describes the page content and includes your primary keyword.",
        }
    return None


def _check_thin_content(page: Page) -> dict | None:
    if page.status_code == 200 and page.word_count is not None and page.word_count < 300:
        return {
            "category": "content",
            "severity": "high",
            "title": "Thin content",
            "description": f"The page at {page.path} has only {page.word_count} words. Pages with fewer than 300 words often struggle to rank.",
            "recommendation": "Expand the content to at least 800-1000 words with valuable, relevant information for the user's search intent.",
        }
    return None


def _check_slow_response(page: Page) -> dict | None:
    if page.response_time_ms and page.response_time_ms > 3000:
        return {
            "category": "technical",
            "severity": "high",
            "title": "Slow page response time",
            "description": f"The page at {page.path} took {page.response_time_ms}ms to respond. Google recommends pages load within 2.5 seconds.",
            "recommendation": "Investigate server-side performance. Consider caching, CDN, or optimizing database queries.",
        }
    elif page.response_time_ms and page.response_time_ms > 1500:
        return {
            "category": "technical",
            "severity": "medium",
            "title": "Moderately slow response time",
            "description": f"The page at {page.path} took {page.response_time_ms}ms to respond. Aim for under 1 second.",
            "recommendation": "Review server response time. This isn't critical yet but could impact user experience.",
        }
    return None


def _check_404_page(page: Page) -> dict | None:
    if page.status_code == 404:
        return {
            "category": "technical",
            "severity": "high",
            "title": "Broken page (404)",
            "description": f"The page at {page.path} returns a 404 status. Internal links pointing to this page waste crawl budget and hurt user experience.",
            "recommendation": "Either create content at this URL, set up a 301 redirect to a relevant page, or remove internal links pointing here.",
        }
    return None


def _check_duplicate_title(pages: list[Page]) -> list[dict]:
    """Check for duplicate titles across pages."""
    issues = []
    title_map: dict[str, list[str]] = {}
    for page in pages:
        if page.title and page.status_code == 200:
            key = page.title.strip().lower()
            if key not in title_map:
                title_map[key] = []
            title_map[key].append(page.path)

    for title, paths in title_map.items():
        if len(paths) > 1:
            issues.append({
                "category": "technical",
                "severity": "high",
                "title": "Duplicate title tag",
                "description": f"The title \"{paths[0]}\" is shared by {len(paths)} pages: {', '.join(paths[:5])}. Each page should have a unique title.",
                "recommendation": "Write unique, descriptive titles for each page that reflect its specific content.",
                "affected_url": paths[0],
            })
    return issues


# Aggregate all checks
PAGE_CHECKS = [
    _check_missing_title,
    _check_title_length,
    _check_missing_meta_description,
    _check_meta_description_length,
    _check_missing_h1,
    _check_thin_content,
    _check_slow_response,
    _check_404_page,
]


async def run_agent_analysis(db: AsyncSession, site_id: uuid.UUID) -> AgentRun:
    """Run SEO analysis on all crawled pages for a site."""

    # Create agent run record
    agent_run = AgentRun(site_id=site_id, status="running", trigger="manual")
    db.add(agent_run)
    await db.commit()
    await db.refresh(agent_run)

    try:
        # Get all pages for this site
        result = await db.execute(
            select(Page).where(Page.site_id == site_id).order_by(Page.path)
        )
        pages = list(result.scalars().all())

        if not pages:
            agent_run.status = "completed"
            agent_run.summary = "No pages found to analyze. Run a crawl first."
            agent_run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return agent_run

        issues_created = 0

        # Run per-page checks
        for page in pages:
            for check_fn in PAGE_CHECKS:
                issue_data = check_fn(page)
                if issue_data:
                    issue = Issue(
                        site_id=site_id,
                        page_id=page.id,
                        agent_run_id=agent_run.id,
                        affected_url=page.path,
                        **issue_data,
                    )
                    db.add(issue)
                    issues_created += 1

        # Run cross-page checks
        for issue_data in _check_duplicate_title(pages):
            issue = Issue(
                site_id=site_id,
                agent_run_id=agent_run.id,
                **issue_data,
            )
            db.add(issue)
            issues_created += 1

        # Generate summary
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        # Count from the issues we just created by re-checking
        for page in pages:
            for check_fn in PAGE_CHECKS:
                issue_data = check_fn(page)
                if issue_data:
                    severity_counts[issue_data["severity"]] += 1
        for issue_data in _check_duplicate_title(pages):
            severity_counts[issue_data["severity"]] += 1

        summary_parts = []
        if severity_counts["critical"]:
            summary_parts.append(f"{severity_counts['critical']} critical")
        if severity_counts["high"]:
            summary_parts.append(f"{severity_counts['high']} high")
        if severity_counts["medium"]:
            summary_parts.append(f"{severity_counts['medium']} medium")
        if severity_counts["low"]:
            summary_parts.append(f"{severity_counts['low']} low")

        agent_run.status = "completed"
        agent_run.pages_analyzed = len(pages)
        agent_run.issues_found = issues_created
        agent_run.summary = f"Analyzed {len(pages)} pages. Found {issues_created} issues: {', '.join(summary_parts)}."
        agent_run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(agent_run)

        return agent_run

    except Exception as e:
        agent_run.status = "failed"
        agent_run.error = str(e)
        agent_run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return agent_run
