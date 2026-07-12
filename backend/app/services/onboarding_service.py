from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User, Workspace
from app.models.onboarding import OnboardingState
from app.models.site import Site
from app.schemas.onboarding import ONBOARDING_STEPS, OnboardingResponse
from app.schemas.site import SiteCreate
from app.services.site_service import create_site


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


def _text(answers: dict[str, Any], key: str) -> str | None:
    value = answers.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


async def _apply_profile(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    answers: dict[str, Any],
) -> None:
    user = await db.get(User, user_id)
    workspace = await db.get(Workspace, workspace_id)
    if not user or not workspace:
        raise OnboardingServiceError("Workspace identity is unavailable", 404)
    full_name = _text(answers, "full_name")
    company_name = _text(answers, "company_name")
    if full_name:
        user.name = full_name
    if company_name:
        workspace.name = company_name


async def _apply_site(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    answers: dict[str, Any],
) -> Site:
    website_url = _text(answers, "website_url")
    if not website_url:
        raise OnboardingServiceError("Website URL is required")
    try:
        site_data = SiteCreate(domain=website_url, name=_text(answers, "site_name"))
    except ValueError as exc:
        raise OnboardingServiceError("Enter a valid website URL") from exc

    existing = await db.scalar(select(Site).where(Site.domain == site_data.domain))
    if existing:
        if existing.workspace_id != workspace_id:
            raise OnboardingServiceError(
                "This domain already exists in another workspace. Use the verified site-claim flow.",
                409,
            )
        if site_data.name:
            existing.name = site_data.name
        return existing

    return await create_site(db, site_data, workspace_id)


async def _apply_cms(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    all_answers: dict[str, Any],
    answers: dict[str, Any],
) -> None:
    cms = _text(answers, "cms")
    if cms not in {"github", "wordpress"}:
        return
    site_answers = all_answers.get("site")
    if not isinstance(site_answers, dict):
        return
    website_url = _text(site_answers, "website_url")
    if not website_url:
        return
    try:
        domain = SiteCreate(domain=website_url).domain
    except ValueError:
        return
    site = await db.scalar(
        select(Site).where(Site.domain == domain, Site.workspace_id == workspace_id)
    )
    if site:
        site.cms = cms


async def _apply_step_effects(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    step: str,
    answers: dict[str, Any],
    all_answers: dict[str, Any],
) -> None:
    if step == "profile":
        await _apply_profile(
            db,
            workspace_id=workspace_id,
            user_id=user_id,
            answers=answers,
        )
    elif step == "site":
        await _apply_site(db, workspace_id=workspace_id, answers=answers)
    elif step == "cms":
        await _apply_cms(
            db,
            workspace_id=workspace_id,
            all_answers=all_answers,
            answers=answers,
        )


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
    merged_answers = merge_step_answers(state.answers, step=step, answers=answers)
    await _apply_step_effects(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        step=step,
        answers=answers,
        all_answers=merged_answers,
    )
    state.answers = merged_answers

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
