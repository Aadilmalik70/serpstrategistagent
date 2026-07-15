import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace
from app.schemas.onboarding import OnboardingCompleteRequest, OnboardingResponse, OnboardingStepUpdate
from app.services.onboarding_launch_service import (
    google_launch_connection,
    queue_initial_crawl,
    run_google_baseline_background,
)
from app.services.onboarding_service import (
    OnboardingServiceError,
    complete_onboarding,
    get_or_create_onboarding,
    onboarding_response,
    save_onboarding_step,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _service_error(exc: OnboardingServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _mark_launch_failed(db: AsyncSession, state, error_type: str) -> None:
    state.status = "in_progress"
    state.current_step = "review"
    state.completed_at = None
    state.completed_steps = [step for step in (state.completed_steps or []) if step != "review"]
    state.answers = {
        **(state.answers or {}),
        "launch": {"status": "failed", "error_type": error_type},
    }
    await db.commit()
    await db.refresh(state)


@router.get("", response_model=OnboardingResponse)
async def get_onboarding(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    state = await get_or_create_onboarding(
        db,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
    )
    return onboarding_response(state)


@router.put("/step", response_model=OnboardingResponse)
async def save_step(
    data: OnboardingStepUpdate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    try:
        state = await save_onboarding_step(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            step=data.step,
            answers=data.answers,
            complete_step=data.complete_step,
            next_step=data.next_step,
        )
    except OnboardingServiceError as exc:
        raise _service_error(exc) from exc
    return onboarding_response(state)


@router.post("/complete", response_model=OnboardingResponse)
async def finish_onboarding(
    data: OnboardingCompleteRequest,
    background_tasks: BackgroundTasks,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    try:
        state = await complete_onboarding(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
    except OnboardingServiceError as exc:
        raise _service_error(exc) from exc

    if not data.launch_operator:
        return onboarding_response(state)

    try:
        site_answers = (state.answers or {}).get("site", {})
        site_id_raw = site_answers.get("site_id") if isinstance(site_answers, dict) else None
        if not site_id_raw:
            raise HTTPException(status_code=409, detail="Onboarding site is unavailable")

        try:
            site_id = uuid.UUID(str(site_id_raw))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Onboarding site is invalid") from exc

        job, site, max_pages, created = await queue_initial_crawl(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
        )
        google_connection = await google_launch_connection(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
        if google_connection:
            background_tasks.add_task(run_google_baseline_background, google_connection.id)

        launch = {
            "status": "running",
            "site_id": str(site.id),
            "crawl_job_id": str(job.id),
            "crawl_status": job.status,
            "google_sync": "queued" if google_connection else "not_configured",
            "max_pages": max_pages,
        }
        state.answers = {**(state.answers or {}), "launch": launch}
        await db.commit()
        await db.refresh(state)
        return onboarding_response(state)
    except Exception as exc:
        await _mark_launch_failed(db, state, type(exc).__name__)
        raise
