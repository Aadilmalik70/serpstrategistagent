"""Fix executor — executes approved fix actions via GitHub or WordPress."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fix_action import FixAction
from app.models.site import Site
from app.services.fix_governance import (
    HIGH_RISK_PATH_KEYWORDS,
    RiskAssessment,
    ValidationCheckResult,
    decide_execution_mode,
    run_sandbox_checks,
)
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
        governance = (fix.fix_content or {}).get("governance", {})
        validation = await _run_sandbox_validation(site, fix)
        mode = decide_execution_mode(
            validation_report=validation["report"],
            risk=_create_risk_assessment_from_governance(governance),
            autonomous_enabled=True,
        )
        if mode == "blocked":
            fix.status = "failed"
            fix.execution_result = {
                "error": "Sandbox validation failed",
                "validation": validation["data"],
                "audit": _build_audit_log(fix),
            }
            await db.commit()
            return {"error": "Sandbox validation failed", "validation": validation["data"]}

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

        fix.execution_result = {
            **result,
            "validation": validation["data"],
            "governance": governance,
            "audit": _build_audit_log(fix),
            "rollback": {
                "available": fix.action_type in ("github_pr", "wordpress_update"),
                "strategy": "revert_pr_or_restore_previous_content",
            },
            "learning_signal": {
                "status": "success" if "error" not in result else "failed",
                "risk_level": governance.get("risk_level", "unknown"),
                "recommended_mode": governance.get("recommended_mode"),
            },
        }
        await db.commit()

        return result

    except Exception as e:
        logger.error(f"Failed to execute fix {fix_action_id}: {e}")
        fix.status = "failed"
        fix.execution_result = {"error": str(e), "audit": _build_audit_log(fix)}
        await db.commit()
        return {"error": str(e)}


def _create_risk_assessment_from_governance(governance: dict):
    level = governance.get("risk_level", "medium")
    return RiskAssessment(
        score=int(governance.get("risk_score", 0) or 0),
        level=level,
        reasons=list(governance.get("risk_reasons", [])),
        requires_human_approval=level == "high",
    )


def _build_audit_log(fix: FixAction) -> dict:
    content = fix.fix_content or {}
    return {
        "fix_id": str(fix.id),
        "target_path": fix.target_path,
        "action_type": fix.action_type,
        "blocked_paths_policy": list(HIGH_RISK_PATH_KEYWORDS),
        "max_changed_files": content.get("policy", {}).get("max_changed_files", 5),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _run_sandbox_validation(site: Site, fix: FixAction) -> dict:
    checks: list[ValidationCheckResult] = []
    content = fix.fix_content or {}
    sandbox = content.get("sandbox", {})

    if fix.action_type == "github_pr":
        if site.github_repo and site.github_token:
            github = GitHubIntegration(repo=site.github_repo, token=site.github_token)
            verify = await github.verify_connection()
            checks.append(
                ValidationCheckResult(
                    name="connector",
                    passed=bool(verify.get("connected")),
                    message=verify.get("error"),
                    details=verify,
                )
            )
        else:
            checks.append(ValidationCheckResult(name="connector", passed=False, message="GitHub not configured"))
    elif fix.action_type == "wordpress_update":
        if site.wordpress_url and site.wordpress_user and site.wordpress_app_password:
            wp = WordPressIntegration(
                site_url=site.wordpress_url,
                username=site.wordpress_user,
                app_password=site.wordpress_app_password,
            )
            verify = await wp.verify_connection()
            checks.append(
                ValidationCheckResult(
                    name="connector",
                    passed=bool(verify.get("connected")),
                    message=verify.get("error"),
                    details=verify,
                )
            )
        else:
            checks.append(ValidationCheckResult(name="connector", passed=False, message="WordPress not configured"))

    checks.extend(
        [
            ValidationCheckResult(
                name="build_install",
                passed=bool(sandbox.get("build_passed", True)),
                message=sandbox.get("build_message"),
            ),
            ValidationCheckResult(
                name="smoke_test",
                passed=bool(sandbox.get("smoke_passed", True)),
                message=sandbox.get("smoke_message"),
            ),
            ValidationCheckResult(
                name="seo_checks",
                passed=bool(sandbox.get("seo_passed", True)),
                message=sandbox.get("seo_message"),
            ),
        ]
    )

    report = run_sandbox_checks(checks)
    return {
        "report": report,
        "data": {
            "passed": report.passed,
            "failed_checks": report.failed_checks,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "message": check.message,
                    "details": check.details,
                }
                for check in report.checks
            ],
        },
    }


async def _execute_github_pr(site: Site, fix: FixAction) -> dict:
    """Execute a GitHub PR fix."""
    if not site.github_repo or not site.github_token:
        return {"error": "GitHub not configured for this site"}

    content = fix.fix_content or {}
    file_path = content.get("file_path") or fix.target_path
    code_snippet = content.get("code_snippet") or content.get("new_content")
    commit_message = content.get("commit_message") or f"fix(seo): {fix.title}"

    if not file_path or not code_snippet:
        return {"error": "Missing file_path or code_snippet in fix_content"}

    github = GitHubIntegration(repo=site.github_repo, token=site.github_token)

    # Fetch existing file content from repo
    existing_content = await github.get_file_content(file_path)

    # Use LLM to merge snippet into existing file (or generate new file)
    llm = _get_llm()
    if not llm:
        return {"error": "No LLM available for code merging"}

    if existing_content:
        prompt = MERGE_PROMPT.format(
            file_path=file_path,
            existing_content=existing_content,
            code_snippet=code_snippet,
            description=fix.description or fix.title,
        )
    else:
        prompt = NEW_FILE_PROMPT.format(
            tech_stack=site.tech_stack or "nextjs",
            file_path=file_path,
            code_snippet=code_snippet,
            description=fix.description or fix.title,
        )

    response = await llm.ainvoke(prompt)
    final_content = response.content.strip()

    # Strip code fences if LLM added them
    if final_content.startswith("```"):
        lines = final_content.split("\n")
        # Remove first line (```lang) and last line (```)
        if lines[-1].strip() == "```":
            final_content = "\n".join(lines[1:-1])
        else:
            final_content = "\n".join(lines[1:])

    logger.info(f"Generated merged file for {file_path} ({len(final_content)} chars)")

    # Generate a unique branch name
    branch_name = f"seo-fix/{fix.id.hex[:8]}"

    result = await github.create_fix_pr(
        file_path=file_path,
        new_content=final_content,
        branch_name=branch_name,
        title=fix.title,
        description=fix.description or f"Automated SEO fix for {site.domain}",
    )

    return result


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
