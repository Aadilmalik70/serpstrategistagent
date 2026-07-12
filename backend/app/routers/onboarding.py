from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace
from app.schemas.onboarding import (
    OnboardingCompleteRequest,
    OnboardingStateResponse,
    OnboardingStepUpdate,
)
from app.services.onboarding_service import (
    OnboardingServiceError,
    complete_onboarding,
    get_or_create_onboarding,
    update_onboarding_step,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _service_error(exc: OnboardingServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("", response_model=OnboardingStateResponse)
async def get_onboarding_state(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStateResponse:
    return await get_or_create_onboarding(
        db,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
    )


@router.put("/step", response_model=OnboardingStateResponse)
async def save_onboarding_step(
    data: OnboardingStepUpdate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStateResponse:
    try:
        return await update_onboarding_step(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            step=data.step,
            step_data=data.data,
            complete_step=data.complete_step,
            next_step=data.next_step,
        )
    except OnboardingServiceError as exc:
        raise _service_error(exc) from exc


@router.post("/complete", response_model=OnboardingStateResponse)
async def finish_onboarding(
    data: OnboardingCompleteRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStateResponse:
    del data
    try:
        return await complete_onboarding(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
    except OnboardingServiceError as exc:
        raise _service_error(exc) from exc
