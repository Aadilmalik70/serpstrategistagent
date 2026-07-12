from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingState
from app.schemas.onboarding import ONBOARDING_STEPS, OnboardingStateResponse


class OnboardingServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def onboarding_response(state: OnboardingState) -> OnboardingStateResponse:
    return OnboardingStateResponse(
        id=state.id,
        workspace_id=state.workspace_id,
        user_id=state.user_id,
        version=state.version,
        current_step=state.current_step,
        completed_steps=list(state.completed_steps or []),
        data=dict(state.data or {}),
        status=state.status,
        started_at=state.started_at,
        completed_at=state.completed_at,
        updated_at=state.updated_at,
    )


async def get_or_create_onboarding(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OnboardingStateResponse:
    state = await db.scalar(
        select(OnboardingState).where(
            OnboardingState.workspace_id == workspace_id,
            OnboardingState.user_id == user_id,
        )
    )
    if not state:
        state = OnboardingState(workspace_id=workspace_id, user_id=user_id)
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return onboarding_response(state)


async def update_onboarding_step(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    step: str,
    step_data: dict[str, Any],
    complete_step: bool,
    next_step: str | None,
) -> OnboardingStateResponse:
    state = await db.scalar(
        select(OnboardingState).where(
            OnboardingState.workspace_id == workspace_id,
            OnboardingState.user_id == user_id,
        )
    )
    if not state:
        state = OnboardingState(workspace_id=workspace_id, user_id=user_id)
        db.add(state)
        await db.flush()

    if state.status == "completed":
        raise OnboardingServiceError("Completed onboarding cannot be modified", 409)

    merged = dict(state.data or {})
    merged[step] = dict(step_data)
    completed = list(state.completed_steps or [])
    if complete_step and step not in completed:
        completed.append(step)
    completed = [item for item in ONBOARDING_STEPS if item in completed]

    state.data = merged
    state.completed_steps = completed
    state.current_step = next_step or step
    await db.commit()
    await db.refresh(state)
    return onboarding_response(state)


async def complete_onboarding(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OnboardingStateResponse:
    state = await db.scalar(
        select(OnboardingState).where(
            OnboardingState.workspace_id == workspace_id,
            OnboardingState.user_id == user_id,
        )
    )
    if not state:
        raise OnboardingServiceError("Onboarding has not been started", 404)

    required = {"profile", "site", "goals"}
    missing = sorted(required - set(state.completed_steps or []))
    if missing:
        raise OnboardingServiceError(
            f"Complete required onboarding steps first: {', '.join(missing)}",
            409,
        )

    now = datetime.now(timezone.utc)
    state.status = "completed"
    state.current_step = "review"
    state.completed_at = now
    await db.commit()
    await db.refresh(state)
    return onboarding_response(state)
