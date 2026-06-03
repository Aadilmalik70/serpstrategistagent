"""Health score calculation based on issue severity."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue


# Points deducted per issue severity
SEVERITY_WEIGHTS = {
    "critical": 15,
    "high": 8,
    "medium": 3,
    "low": 1,
}


async def calculate_health_score(db: AsyncSession, site_id) -> dict:
    """Calculate SEO health score (0-100) for a site based on open issues.

    Returns dict with score, grade, and breakdown.
    """
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

    # Grade based on score
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
