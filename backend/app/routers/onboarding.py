from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace
from app.schemas.onboarding import OnboardingCompleteRequest, OnboardingResponse, OnboardingStepUpdate
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
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    del data
    try:
        state = await complete_onboarding(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
    except OnboardingServiceError as exc:
        raise _service_error(exc) from exc
    return onboarding_response(state)
