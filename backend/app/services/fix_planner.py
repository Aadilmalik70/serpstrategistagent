"""Fix planner — LLM generates concrete fixes for SEO issues."""
import logging
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.site import Site
from app.models.fix_action import FixAction
from app.services.llm_analyzer import _get_llm

logger = logging.getLogger(__name__)


FIX_PLAN_PROMPT = """You are an SEO fix generator. Given an SEO issue and the website's technology stack, generate a concrete fix.

SITE INFO:
- Domain: {domain}
- Tech Stack: {tech_stack}
- CMS: {cms}

ISSUE:
- Title: {title}
- Description: {description}
- Severity: {severity}
- Category: {category}
- Affected URL: {affected_url}
- Current recommendation: {recommendation}

Based on the technology, generate a fix. The site has a connected GitHub repo.

For code-based fixes (Next.js/React), return:
- action_type: "github_pr"
- file_path: which file to create/modify (e.g., "app/layout.tsx", "next.config.js")
- code_snippet: ONLY the specific code to add or change (not the full file). Use single-line escaped format.
- commit_message: short commit message

IMPORTANT: Keep code_snippet SHORT — just the relevant metadata/component code, not entire files.
All string values must be on ONE line (escape newlines as \\n).

RESPOND IN VALID JSON ONLY (all on single lines, no actual newlines in string values):
{{
  "action_type": "github_pr",
  "title": "Short fix title",
  "description": "What this fix does",
  "fix_content": {{
    "file_path": "app/layout.tsx",
    "code_snippet": "export const metadata = {{ title: 'My Site', description: 'My description' }}",
    "commit_message": "fix(seo): add missing meta description"
  }},
  "target_path": "app/layout.tsx"
}}
"""


async def generate_fix_plan(
    db: AsyncSession,
    issue_id: uuid.UUID,
) -> FixAction | None:
    """Generate a fix plan for a specific issue using LLM.

    Returns the created FixAction (status=pending) or None if generation fails.
    """
    # Load issue and site
    issue = await db.get(Issue, issue_id)
    if not issue:
        logger.error(f"Issue {issue_id} not found")
        return None

    site = await db.get(Site, issue.site_id)
    if not site:
        logger.error(f"Site for issue {issue_id} not found")
        return None

    # Determine what action types are available
    has_github = bool(site.github_repo and site.github_token)
    has_wordpress = bool(site.wordpress_url and site.wordpress_user and site.wordpress_app_password)

    llm = _get_llm()
    if not llm:
        logger.error("No LLM available for fix planning")
        return None

    prompt = FIX_PLAN_PROMPT.format(
        domain=site.domain,
        tech_stack=site.tech_stack or "unknown",
        cms=site.cms or "none",
        title=issue.title,
        description=issue.description,
        severity=issue.severity,
        category=issue.category,
        affected_url=issue.affected_url or site.domain,
        recommendation=issue.recommendation or "None provided",
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        logger.info(f"LLM fix plan raw response (first 500 chars): {content[:500]}")

        # Parse JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Fix common LLM JSON issues: unescaped newlines in string values
        # Replace actual newlines inside strings with \n escape
        import re
        content = re.sub(r'(?<=": ")(.*?)(?="[,\s}])', lambda m: m.group(0).replace('\n', '\\n').replace('\r', ''), content, flags=re.DOTALL)

        try:
            fix_data = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: try to extract just the key fields manually
            action_type_match = re.search(r'"action_type"\s*:\s*"([^"]+)"', content)
            title_match = re.search(r'"title"\s*:\s*"([^"]+)"', content)
            desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', content)
            file_path_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', content)

            if not action_type_match:
                raise ValueError("Could not parse action_type from LLM response")

            fix_data = {
                "action_type": action_type_match.group(1),
                "title": title_match.group(1) if title_match else "SEO Fix",
                "description": desc_match.group(1) if desc_match else "",
                "fix_content": {"file_path": file_path_match.group(1) if file_path_match else None, "new_content": "See fix description"},
                "target_path": file_path_match.group(1) if file_path_match else None,
            }
    except Exception as e:
        logger.error(f"Failed to generate fix plan for issue {issue_id}: {e}")
        return None

    # Validate action_type is feasible
    action_type = fix_data.get("action_type", "recommendation")
    if action_type == "github_pr" and not has_github:
        action_type = "recommendation"
    if action_type == "wordpress_update" and not has_wordpress:
        action_type = "recommendation"

    # Create the fix action
    fix_action = FixAction(
        site_id=site.id,
        issue_id=issue.id,
        action_type=action_type,
        status="pending",
        title=fix_data.get("title", issue.title),
        description=fix_data.get("description", ""),
        fix_content=fix_data.get("fix_content"),
        target_path=fix_data.get("target_path"),
    )
    db.add(fix_action)
    await db.commit()
    await db.refresh(fix_action)

    logger.info(f"Created fix plan {fix_action.id} ({action_type}) for issue {issue_id}")
    return fix_action


async def generate_bulk_fix_plans(
    db: AsyncSession,
    site_id: uuid.UUID,
    max_issues: int = 10,
) -> list[FixAction]:
    """Generate fix plans for top issues of a site.

    Prioritizes by severity: critical > high > medium > low.
    Only processes issues with status='open' that don't already have fix_actions.
    """
    # Get open issues without existing fix plans, ordered by severity
    severity_order = ["critical", "high", "medium", "low"]

    result = await db.execute(
        select(Issue)
        .where(Issue.site_id == site_id, Issue.status == "open")
        .order_by(
            # Sort by severity priority
            Issue.severity
        )
    )
    issues = result.scalars().all()

    # Sort by severity priority manually
    issues = sorted(issues, key=lambda i: severity_order.index(i.severity) if i.severity in severity_order else 99)

    # Filter out issues that already have fix_actions
    issues_to_fix = []
    for issue in issues[:max_issues]:
        existing = await db.execute(
            select(FixAction).where(FixAction.issue_id == issue.id)
        )
        if not existing.scalar_one_or_none():
            issues_to_fix.append(issue)

    fix_actions = []
    for issue in issues_to_fix[:max_issues]:
        fix = await generate_fix_plan(db, issue.id)
        if fix:
            fix_actions.append(fix)

    logger.info(f"Generated {len(fix_actions)} fix plans for site {site_id}")
    return fix_actions
