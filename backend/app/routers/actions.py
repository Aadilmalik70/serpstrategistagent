"""Prototype action APIs with Phase 2 tenant authorization boundaries."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.fix_action import FixAction
from app.models.issue import Issue
from app.models.site import Site
from app.services.fix_executor import execute_fix_action
from app.services.fix_planner import generate_bulk_fix_plans, generate_fix_plan
from app.services.github_integration import GitHubIntegration
from app.services.site_service import get_site_by_id
from app.services.tech_detector import detect_tech_stack
from app.services.wordpress_integration import WordPressIntegration

router = APIRouter(prefix="/actions", tags=["actions"])


class TechDetectionResponse(BaseModel):
    tech_stack: str
    cms: str
    signals: list[str]


class IntegrationConfig(BaseModel):
    github_repo: str | None = None
    github_token: str | None = None
    wordpress_url: str | None = None
    wordpress_user: str | None = None
    wordpress_app_password: str | None = None
    autonomous_enabled: bool | None = None


class FixActionResponse(BaseModel):
    id: str
    site_id: str
    issue_id: str
    action_type: str
    status: str
    title: str
    description: str | None
    fix_content: dict | None
    target_path: str | None
    execution_result: dict | None
    created_at: str | None
    approved_at: str | None
    executed_at: str | None


class ApprovalRequest(BaseModel):
    action: str


class CodexTaskRequest(BaseModel):
    task: str
    repo_path: str | None = None


async def _require_site(
    db: AsyncSession,
    context: WorkspaceContext,
    site_id: uuid.UUID,
) -> Site:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _require_issue(
    db: AsyncSession,
    context: WorkspaceContext,
    issue_id: uuid.UUID,
) -> Issue:
    issue = (
        await db.execute(
            select(Issue)
            .join(Site, Site.id == Issue.site_id)
            .where(Issue.id == issue_id, Site.workspace_id == context.workspace.id)
        )
    ).scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


async def _require_fix(
    db: AsyncSession,
    context: WorkspaceContext,
    fix_id: uuid.UUID,
) -> FixAction:
    fix = (
        await db.execute(
            select(FixAction)
            .join(Site, Site.id == FixAction.site_id)
            .where(FixAction.id == fix_id, Site.workspace_id == context.workspace.id)
        )
    ).scalar_one_or_none()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix action not found")
    return fix


@router.post("/detect-tech/{site_id}", response_model=TechDetectionResponse)
async def detect_technology(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, site_id)
    result = await detect_tech_stack(db, site_id)
    site.tech_stack = result["tech_stack"]
    site.cms = result["cms"]
    await db.commit()
    return result


@router.get("/integrations/{site_id}")
async def get_integrations(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    site = await _require_site(db, context, site_id)
    return {
        "github_repo": site.github_repo,
        "github_connected": bool(site.github_repo and site.github_token),
        "wordpress_url": site.wordpress_url,
        "wordpress_connected": bool(site.wordpress_url and site.wordpress_user and site.wordpress_app_password),
        "tech_stack": site.tech_stack,
        "cms": site.cms,
        "autonomous_enabled": bool((site.site_context or {}).get("autonomous_enabled", False)),
    }


@router.put("/integrations/{site_id}")
async def update_integrations(
    site_id: uuid.UUID,
    config: IntegrationConfig,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, site_id)

    if config.github_repo is not None:
        site.github_repo = config.github_repo
    if config.github_token is not None:
        site.github_token = config.github_token
    if config.wordpress_url is not None:
        site.wordpress_url = config.wordpress_url
    if config.wordpress_user is not None:
        site.wordpress_user = config.wordpress_user
    if config.wordpress_app_password is not None:
        site.wordpress_app_password = config.wordpress_app_password
    if config.autonomous_enabled is not None:
        site.site_context = {**(site.site_context or {}), "autonomous_enabled": config.autonomous_enabled}

    await db.commit()
    return {"status": "updated"}


@router.post("/integrations/{site_id}/verify")
async def verify_integrations(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, site_id)
    results: dict[str, dict] = {}

    if site.github_repo and site.github_token:
        results["github"] = await GitHubIntegration(
            repo=site.github_repo,
            token=site.github_token,
        ).verify_connection()
    else:
        results["github"] = {"connected": False, "reason": "Not configured"}

    if site.wordpress_url and site.wordpress_user and site.wordpress_app_password:
        results["wordpress"] = await WordPressIntegration(
            site_url=site.wordpress_url,
            username=site.wordpress_user,
            app_password=site.wordpress_app_password,
        ).verify_connection()
    else:
        results["wordpress"] = {"connected": False, "reason": "Not configured"}

    return results


@router.post("/fix-plan/{issue_id}", response_model=FixActionResponse)
async def create_fix_plan(
    issue_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    await _require_issue(db, context, issue_id)
    fix = await generate_fix_plan(db, issue_id)
    if not fix:
        raise HTTPException(status_code=500, detail="Failed to generate fix plan")
    return _fix_to_response(fix)


@router.post("/fix-plan-bulk/{site_id}")
async def create_bulk_fix_plans(
    site_id: uuid.UUID,
    max_issues: int = 10,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    await _require_site(db, context, site_id)
    fixes = await generate_bulk_fix_plans(db, site_id, max_issues=max_issues)
    return {"generated": len(fixes), "fix_actions": [_fix_to_response(fix) for fix in fixes]}


@router.get("/fixes/{site_id}")
async def list_fix_actions(
    site_id: uuid.UUID,
    status: str | None = None,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    query = select(FixAction).where(FixAction.site_id == site_id)
    if status:
        query = query.where(FixAction.status == status)
    fixes = (await db.execute(query.order_by(FixAction.created_at.desc()))).scalars().all()
    return [_fix_to_response(fix) for fix in fixes]


@router.get("/fix/{fix_id}", response_model=FixActionResponse)
async def get_fix_action(
    fix_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return _fix_to_response(await _require_fix(db, context, fix_id))


@router.post("/fix/{fix_id}/approve")
async def approve_fix_action(
    fix_id: uuid.UUID,
    request: ApprovalRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    fix = await _require_fix(db, context, fix_id)
    if fix.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Fix action is '{fix.status}', can only approve/reject 'pending'",
        )

    if request.action == "approve":
        fix.status = "approved"
        fix.approved_at = datetime.now(timezone.utc)
    elif request.action == "reject":
        fix.status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    await db.commit()
    return {"status": fix.status, "fix_id": str(fix_id)}


@router.post("/fix/{fix_id}/execute")
async def execute_fix(
    fix_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    await _require_fix(db, context, fix_id)
    result = await execute_fix_action(db, fix_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/approve-and-execute/{fix_id}")
async def approve_and_execute(
    fix_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    fix = await _require_fix(db, context, fix_id)
    if fix.status != "pending":
        raise HTTPException(status_code=400, detail=f"Fix action is '{fix.status}', must be 'pending'")

    governance = (fix.fix_content or {}).get("governance", {})
    if governance.get("requires_human_approval"):
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-execute. This fix is high risk and requires manual review before execution.",
        )

    fix.status = "approved"
    fix.approved_at = datetime.now(timezone.utc)
    await db.commit()
    result = await execute_fix_action(db, fix_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/codex/{site_id}")
async def run_codex_task(
    site_id: uuid.UUID,
    request: CodexTaskRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    # The application middleware returns HTTP 410 before this prototype route can execute.
    require_workspace_role(context, "owner", "admin")
    await _require_site(db, context, site_id)
    raise HTTPException(status_code=410, detail="Direct Codex execution is disabled")


@router.get("/metrics/{site_id}")
async def get_fix_metrics(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    fixes = list((await db.execute(select(FixAction).where(FixAction.site_id == site_id))).scalars().all())
    total = len(fixes)
    completed = sum(1 for fix in fixes if fix.status == "completed")
    failed = sum(1 for fix in fixes if fix.status == "failed")
    pending = sum(1 for fix in fixes if fix.status == "pending")
    approved = sum(1 for fix in fixes if fix.status == "approved")
    auto_executed = sum(
        1
        for fix in fixes
        if (fix.execution_result or {}).get("governance", {}).get("recommended_mode") == "auto_execute"
    )
    return {
        "site_id": str(site_id),
        "validated_fixes_executed": completed,
        "failure_rate": (failed / total) if total else 0,
        "approval_bypass_rate": (auto_executed / total) if total else 0,
        "issue_resolution_speed_proxy": completed,
        "execution_summary": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "approved": approved,
        },
    }


def _fix_to_response(fix: FixAction) -> dict:
    return {
        "id": str(fix.id),
        "site_id": str(fix.site_id),
        "issue_id": str(fix.issue_id),
        "action_type": fix.action_type,
        "status": fix.status,
        "title": fix.title,
        "description": fix.description,
        "fix_content": fix.fix_content,
        "target_path": fix.target_path,
        "execution_result": fix.execution_result,
        "created_at": fix.created_at.isoformat() if fix.created_at else None,
        "approved_at": fix.approved_at.isoformat() if fix.approved_at else None,
        "executed_at": fix.executed_at.isoformat() if fix.executed_at else None,
    }
