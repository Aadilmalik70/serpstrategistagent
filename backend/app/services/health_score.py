"""Health score calculation based on issue severity."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.page import Page


SEVERITY_WEIGHTS = {
    "critical": 15,
    "high": 8,
    "medium": 3,
    "low": 1,
}


async def calculate_health_score(db: AsyncSession, site_id) -> dict:
    """Calculate SEO health only after at least one page has been crawled."""
    page_count = await db.scalar(select(func.count(Page.id)).where(Page.site_id == site_id))
    if int(page_count or 0) == 0:
        return {
            "score": None,
            "grade": None,
            "breakdown": {
                severity: {"count": 0, "deduction": 0}
                for severity in SEVERITY_WEIGHTS
            },
            "total_issues": 0,
            "reason": "Run a successful crawl before calculating site health.",
        }

    result = await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.site_id == site_id, Issue.status == "open")
        .group_by(Issue.severity)
    )
    counts = dict(result.all())

    total_deductions = 0
    breakdown = {}
    for severity, weight in SEVERITY_WEIGHTS.items():
        count = counts.get(severity, 0)
        deduction = count * weight
        total_deductions += deduction
        breakdown[severity] = {"count": count, "deduction": deduction}

    score = max(0, 100 - total_deductions)
    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "breakdown": breakdown,
        "total_issues": sum(counts.values()),
    }
