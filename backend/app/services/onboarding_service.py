from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingState
from app.schemas.onboarding import ONBOARDING_STEPS, OnboardingResponse


class OnboardingServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def onboarding_response(state: OnboardingState) -> OnboardingResponse:
    completed = [step for step in state.completed_steps if step in ONBOARDING_STEPS]
    percent = round((len(set(completed)) / len(ONBOARDING_STEPS)) * 100)
    return OnboardingResponse(
        id=state.id,
        workspace_id=state.workspace_id,
        user_id=state.user_id,
        onboarding_version=state.onboarding_version,
        current_step=state.current_step,
        completed_steps=completed,
        answers=state.answers or {},
        status=state.status,
        started_at=state.started_at,
        updated_at=state.updated_at,
        completed_at=state.completed_at,
        completion_percent=percent,
    )


async def get_or_create_onboarding(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OnboardingState:
    state = await db.scalar(
        select(OnboardingState).where(
            OnboardingState.workspace_id == workspace_id,
            OnboardingState.user_id == user_id,
        )
    )
    if state:
        return state

    state = OnboardingState(
        workspace_id=workspace_id,
        user_id=user_id,
        current_step="profile",
        completed_steps=[],
        answers={},
        status="in_progress",
    )
    db.add(state)
    await db.commit()
    await db.refresh(state)
    return state


def merge_step_answers(
    existing: dict[str, Any],
    *,
    step: str,
    answers: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing or {})
    previous = merged.get(step)
    step_answers = dict(previous) if isinstance(previous, dict) else {}
    step_answers.update(answers)
    merged[step] = step_answers
    return merged


async def save_onboarding_step(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    step: str,
    answers: dict[str, Any],
    complete_step: bool,
    next_step: str | None,
) -> OnboardingState:
    if step not in ONBOARDING_STEPS:
        raise OnboardingServiceError("Unknown onboarding step")
    if next_step and next_step not in ONBOARDING_STEPS:
        raise OnboardingServiceError("Unknown next onboarding step")

    state = await get_or_create_onboarding(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    state.answers = merge_step_answers(state.answers, step=step, answers=answers)

    completed = list(dict.fromkeys(state.completed_steps or []))
    if complete_step and step not in completed:
        completed.append(step)
    state.completed_steps = completed

    if next_step:
        state.current_step = next_step
    elif complete_step:
        index = ONBOARDING_STEPS.index(step)
        state.current_step = ONBOARDING_STEPS[min(index + 1, len(ONBOARDING_STEPS) - 1)]
    else:
        state.current_step = step

    state.status = "in_progress"
    state.completed_at = None
    await db.commit()
    await db.refresh(state)
    return state


async def complete_onboarding(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OnboardingState:
    state = await get_or_create_onboarding(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
    )
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
    if "review" not in state.completed_steps:
        state.completed_steps = [*state.completed_steps, "review"]
    await db.commit()
    await db.refresh(state)
    return state
