"""Fix executor — executes approved fix actions via Codex, GitHub, or WordPress."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fix_action import FixAction
from app.models.site import Site
from app.services.codex_agent import execute_fix_with_codex
from app.services.github_integration import GitHubIntegration
from app.services.llm_analyzer import _get_llm
from app.services.wordpress_integration import WordPressIntegration

logger = logging.getLogger(__name__)

MERGE_PROMPT = """You are a code editor. You have an existing file and a code snippet that needs to be applied as a fix.

EXISTING FILE ({file_path}):
```
{existing_content}
```

CODE SNIPPET TO APPLY:
```
{code_snippet}
```

FIX DESCRIPTION: {description}

Your job: Return the COMPLETE updated file content with the fix properly integrated.
Rules:
- Preserve ALL existing code that isn't being replaced
- Add necessary imports if the snippet requires them
- Place the code in the correct location within the file structure
- Ensure the result is valid, working code
- Return ONLY the file content, no explanation, no code fences

OUTPUT THE COMPLETE FILE CONTENT:"""

NEW_FILE_PROMPT = """You are a code generator for a {tech_stack} project.

Create a new file at path: {file_path}

Based on this code snippet / requirement:
```
{code_snippet}
```

FIX DESCRIPTION: {description}

Generate a complete, valid file. Return ONLY the file content, no explanation, no code fences.

OUTPUT THE COMPLETE FILE CONTENT:"""


async def execute_fix_action(db: AsyncSession, fix_action_id: uuid.UUID) -> dict:
    """Execute an approved fix action.

    Only executes if status == 'approved'.
    Returns the execution result.
    """
    fix = await db.get(FixAction, fix_action_id)
    if not fix:
        return {"error": "Fix action not found"}

    if fix.status != "approved":
        return {"error": f"Fix action is '{fix.status}', must be 'approved' to execute"}

    site = await db.get(Site, fix.site_id)
    if not site:
        return {"error": "Site not found"}

    fix.status = "executing"
    await db.commit()

    try:
        if fix.action_type == "github_pr":
            result = await _execute_github_pr(site, fix)
        elif fix.action_type == "wordpress_update":
            result = await _execute_wordpress_update(site, fix)
        elif fix.action_type == "recommendation":
            result = {"status": "recommendation", "message": "Manual action required"}
        else:
            result = {"error": f"Unknown action type: {fix.action_type}"}

        # Update fix action with result
        if "error" in result:
            fix.status = "failed"
        else:
            fix.status = "completed"
            fix.executed_at = datetime.now(timezone.utc)

        fix.execution_result = result
        await db.commit()

        return result

    except Exception as e:
        logger.error(f"Failed to execute fix {fix_action_id}: {e}")
        fix.status = "failed"
        fix.execution_result = {"error": str(e)}
        await db.commit()
        return {"error": str(e)}


async def _execute_github_pr(site: Site, fix: FixAction) -> dict:
    """Execute a GitHub PR fix using Codex CLI as a coding agent.

    Codex clones the repo, reads the actual code, makes proper edits,
    and creates a PR with the changes.
    """
    if not site.github_repo or not site.github_token:
        return {"error": "GitHub not configured for this site"}

    content = fix.fix_content or {}

    # Build a clear task prompt for Codex (it will figure out the code itself)
    task_prompt = _build_codex_prompt(site, fix, content)

    branch_name = f"seo-fix/{fix.id.hex[:8]}"

    logger.info(f"Delegating fix to Codex: {fix.title} on {site.github_repo}")

    result = await execute_fix_with_codex(
        repo_url=site.github_repo,
        github_token=site.github_token,
        task_prompt=task_prompt,
        branch_name=branch_name,
    )

    return result


def _build_codex_prompt(site: Site, fix: FixAction, content: dict) -> str:
    """Build a clear, actionable prompt for Codex to execute the fix."""
    parts = [
        f"You are fixing an SEO issue on the website {site.domain}.",
        f"Tech stack: {site.tech_stack or 'unknown'}, CMS: {site.cms or 'unknown'}.",
        "",
        f"## Issue",
        f"Title: {fix.title}",
        f"Description: {fix.description or 'No description'}",
    ]

    if fix.target_path:
        parts.append(f"Affected file/path: {fix.target_path}")

    if content.get("file_path"):
        parts.append(f"Target file: {content['file_path']}")

    if content.get("affected_url"):
        parts.append(f"Affected URL: {content['affected_url']}")

    if content.get("current_value"):
        parts.append(f"Current value: {content['current_value']}")

    if content.get("recommended_value"):
        parts.append(f"Recommended value: {content['recommended_value']}")

    if content.get("instructions"):
        parts.append(f"\n## Instructions\n{content['instructions']}")

    parts.append("")
    parts.append("## Task")
    parts.append("Find the relevant file(s) in this repo and make the minimum change needed to fix this SEO issue.")
    parts.append("Do NOT add unnecessary changes. Only fix what's described above.")
    parts.append("Make sure the code compiles and is valid.")

    return "\n".join(parts)


async def _execute_wordpress_update(site: Site, fix: FixAction) -> dict:
    """Execute a WordPress content update."""
    if not site.wordpress_url or not site.wordpress_user or not site.wordpress_app_password:
        return {"error": "WordPress not configured for this site"}

    content = fix.fix_content or {}
    wp = WordPressIntegration(
        site_url=site.wordpress_url,
        username=site.wordpress_user,
        app_password=site.wordpress_app_password,
    )

    update_type = content.get("update_type")
    new_value = content.get("new_value")
    slug = content.get("slug") or fix.target_path

    if not slug:
        return {"error": "No slug/target_path to identify the post"}

    # Find the post by slug
    post = await wp.get_post_by_slug(slug)
    if not post:
        post = await wp.get_page_by_slug(slug)
        if not post:
            return {"error": f"Post/page with slug '{slug}' not found"}
        is_page = True
    else:
        is_page = False

    post_id = post["id"]

    # Build update payload based on update_type
    if update_type == "title":
        updates = {"title": new_value}
    elif update_type == "meta_description":
        result = await wp.update_yoast_meta(
            post_id=post_id,
            description=new_value,
            is_page=is_page,
        )
        return result
    elif update_type == "content":
        updates = {"content": new_value}
    elif update_type == "slug":
        updates = {"slug": new_value}
    else:
        updates = {update_type: new_value} if update_type and new_value else {}

    if not updates:
        return {"error": "No valid update fields"}

    if is_page:
        return await wp.update_page(post_id, updates)
    return await wp.update_post(post_id, updates)
