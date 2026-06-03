"""Phase 3 API — Fix actions, tech detection, integration management."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.site import Site
from app.models.fix_action import FixAction
from app.services.tech_detector import detect_tech_stack
from app.services.fix_planner import generate_fix_plan, generate_bulk_fix_plans
from app.services.fix_executor import execute_fix_action
from app.services.github_integration import GitHubIntegration
from app.services.wordpress_integration import WordPressIntegration

router = APIRouter(prefix="/actions", tags=["actions"])


# === Schemas ===

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
    created_at: str
    approved_at: str | None
    executed_at: str | None

    class Config:
        from_attributes = True


class ApprovalRequest(BaseModel):
    action: str  # "approve" or "reject"


# === Tech Detection ===

@router.post("/detect-tech/{site_id}", response_model=TechDetectionResponse)
async def detect_technology(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Detect the technology stack of a site from crawled pages."""
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    result = await detect_tech_stack(db, site_id)

    # Save to site
    site.tech_stack = result["tech_stack"]
    site.cms = result["cms"]
    await db.commit()

    return result


# === Integration Config ===

@router.get("/integrations/{site_id}")
async def get_integrations(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get integration config for a site (tokens masked)."""
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

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
    db: AsyncSession = Depends(get_db),
):
    """Update integration credentials for a site."""
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

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
async def verify_integrations(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Verify all configured integrations are working."""
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    results = {}

    if site.github_repo and site.github_token:
        github = GitHubIntegration(repo=site.github_repo, token=site.github_token)
        results["github"] = await github.verify_connection()
    else:
        results["github"] = {"connected": False, "reason": "Not configured"}

    if site.wordpress_url and site.wordpress_user and site.wordpress_app_password:
        wp = WordPressIntegration(
            site_url=site.wordpress_url,
            username=site.wordpress_user,
            app_password=site.wordpress_app_password,
        )
        results["wordpress"] = await wp.verify_connection()
    else:
        results["wordpress"] = {"connected": False, "reason": "Not configured"}

    return results


# === Fix Planning ===

@router.post("/fix-plan/{issue_id}", response_model=FixActionResponse)
async def create_fix_plan(issue_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Generate a fix plan for a specific issue."""
    fix = await generate_fix_plan(db, issue_id)
    if not fix:
        raise HTTPException(status_code=500, detail="Failed to generate fix plan")

    return _fix_to_response(fix)


@router.post("/fix-plan-bulk/{site_id}")
async def create_bulk_fix_plans(
    site_id: uuid.UUID,
    max_issues: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Generate fix plans for top issues of a site."""
    fixes = await generate_bulk_fix_plans(db, site_id, max_issues=max_issues)
    return {"generated": len(fixes), "fix_actions": [_fix_to_response(f) for f in fixes]}


# === Fix Actions CRUD ===

@router.get("/fixes/{site_id}")
async def list_fix_actions(
    site_id: uuid.UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List fix actions for a site, optionally filtered by status."""
    query = select(FixAction).where(FixAction.site_id == site_id)
    if status:
        query = query.where(FixAction.status == status)
    query = query.order_by(FixAction.created_at.desc())

    result = await db.execute(query)
    fixes = result.scalars().all()
    return [_fix_to_response(f) for f in fixes]


@router.get("/fix/{fix_id}", response_model=FixActionResponse)
async def get_fix_action(fix_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific fix action by ID."""
    fix = await db.get(FixAction, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix action not found")
    return _fix_to_response(fix)


# === Approval ===

@router.post("/fix/{fix_id}/approve")
async def approve_fix_action(
    fix_id: uuid.UUID,
    request: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a fix action."""
    fix = await db.get(FixAction, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix action not found")

    if fix.status != "pending":
        raise HTTPException(status_code=400, detail=f"Fix action is '{fix.status}', can only approve/reject 'pending'")

    if request.action == "approve":
        fix.status = "approved"
        fix.approved_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "approved", "fix_id": str(fix_id)}
    elif request.action == "reject":
        fix.status = "rejected"
        await db.commit()
        return {"status": "rejected", "fix_id": str(fix_id)}
    else:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")


# === Execution ===

@router.post("/fix/{fix_id}/execute")
async def execute_fix(fix_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Execute an approved fix action."""
    result = await execute_fix_action(db, fix_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/approve-and-execute/{fix_id}")
async def approve_and_execute(fix_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Approve and immediately execute a fix action (single-click)."""
    fix = await db.get(FixAction, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix action not found")

    if fix.status != "pending":
        raise HTTPException(status_code=400, detail=f"Fix action is '{fix.status}', must be 'pending'")

    governance = (fix.fix_content or {}).get("governance", {})
    if governance.get("requires_human_approval"):
        raise HTTPException(status_code=400, detail="Cannot auto-execute. This fix is high/medium risk and requires manual review before execution.")

    fix.status = "approved"
    fix.approved_at = datetime.now(timezone.utc)
    await db.commit()

    result = await execute_fix_action(db, fix_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/metrics/{site_id}")
async def get_fix_metrics(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Operational metrics for autonomous SEO fix execution."""
    result = await db.execute(select(FixAction).where(FixAction.site_id == site_id))
    fixes = list(result.scalars().all())

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


# === Helpers ===

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
