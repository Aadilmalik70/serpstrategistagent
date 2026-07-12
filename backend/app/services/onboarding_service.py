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
from app.services.site_service import create_site, get_site_by_domain, get_site_by_id


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


def _required_text(answers: dict[str, Any], field: str, label: str) -> str:
    value = answers.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OnboardingServiceError(f"{label} is required")
    return value.strip()


async def _apply_profile(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    answers: dict[str, Any],
    complete_step: bool,
) -> dict[str, Any]:
    if not complete_step:
        return answers

    full_name = _required_text(answers, "full_name", "Full name")
    company_name = _required_text(answers, "company_name", "Company or brand")
    _required_text(answers, "role", "Role")
    _required_text(answers, "business_type", "Business type")
    _required_text(answers, "country", "Primary country")
    _required_text(answers, "timezone", "Timezone")

    user = await db.get(User, user_id)
    workspace = await db.get(Workspace, workspace_id)
    if not user or not workspace:
        raise OnboardingServiceError("Workspace identity is unavailable", 404)
    user.name = full_name
    workspace.name = company_name
    return {**answers, "full_name": full_name, "company_name": company_name}


async def _apply_site(
    db: AsyncSession,
    *,
    state: OnboardingState,
    workspace_id: uuid.UUID,
    answers: dict[str, Any],
    complete_step: bool,
) -> dict[str, Any]:
    if not complete_step:
        return answers

    website_url = _required_text(answers, "website_url", "Website URL")
    site_name = _required_text(answers, "site_name", "Display name")
    site_input = SiteCreate(domain=website_url, name=site_name)

    previous_site = (state.answers or {}).get("site", {})
    previous_site_id = previous_site.get("site_id") if isinstance(previous_site, dict) else None
    site: Site | None = None
    if previous_site_id:
        try:
            site = await get_site_by_id(db, uuid.UUID(str(previous_site_id)), workspace_id)
        except ValueError:
            site = None

    domain_owner = await get_site_by_domain(db, site_input.domain)
    if domain_owner and (site is None or domain_owner.id != site.id):
        if domain_owner.workspace_id != workspace_id:
            raise OnboardingServiceError(
                "This domain already belongs to another workspace. Verify or claim it from site settings.",
                409,
            )
        site = domain_owner

    if site is None:
        site = await create_site(db, site_input, workspace_id)
    else:
        site.domain = site_input.domain
        site.name = site_input.name or site_input.domain
        await db.commit()
        await db.refresh(site)

    return {
        **answers,
        "site_id": str(site.id),
        "domain": site.domain,
        "website_url": f"https://{site.domain}",
        "site_name": site.name,
    }


async def _apply_cms(
    db: AsyncSession,
    *,
    state: OnboardingState,
    workspace_id: uuid.UUID,
    answers: dict[str, Any],
    complete_step: bool,
) -> dict[str, Any]:
    if not complete_step:
        return answers
    cms = answers.get("cms")
    if cms not in {"github", "wordpress", "skipped"}:
        raise OnboardingServiceError("Choose GitHub, WordPress, or skip CMS setup")

    site_answers = (state.answers or {}).get("site", {})
    site_id = site_answers.get("site_id") if isinstance(site_answers, dict) else None
    if site_id:
        try:
            site = await get_site_by_id(db, uuid.UUID(str(site_id)), workspace_id)
        except ValueError:
            site = None
        if site:
            site.cms = None if cms == "skipped" else str(cms)
    return {**answers, "cms": cms}


async def _validate_goals(answers: dict[str, Any], complete_step: bool) -> dict[str, Any]:
    if not complete_step:
        return answers
    priorities = answers.get("priorities")
    if not isinstance(priorities, list) or not [item for item in priorities if isinstance(item, str) and item]:
        raise OnboardingServiceError("Choose at least one growth goal")
    return answers


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

    normalized = dict(answers)
    if step == "profile":
        normalized = await _apply_profile(
            db,
            workspace_id=workspace_id,
            user_id=user_id,
            answers=normalized,
            complete_step=complete_step,
        )
    elif step == "site":
        normalized = await _apply_site(
            db,
            state=state,
            workspace_id=workspace_id,
            answers=normalized,
            complete_step=complete_step,
        )
    elif step == "cms":
        normalized = await _apply_cms(
            db,
            state=state,
            workspace_id=workspace_id,
            answers=normalized,
            complete_step=complete_step,
        )
    elif step == "goals":
        normalized = await _validate_goals(normalized, complete_step)

    state.answers = merge_step_answers(state.answers, step=step, answers=normalized)

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

    site_answers = (state.answers or {}).get("site", {})
    site_id = site_answers.get("site_id") if isinstance(site_answers, dict) else None
    if not site_id:
        raise OnboardingServiceError("Add a valid website before launching", 409)
    try:
        site = await get_site_by_id(db, uuid.UUID(str(site_id)), workspace_id)
    except ValueError:
        site = None
    if not site:
        raise OnboardingServiceError("The onboarding website is unavailable", 409)

    now = datetime.now(timezone.utc)
    state.status = "completed"
    state.current_step = "review"
    state.completed_at = now
    if "review" not in state.completed_steps:
        state.completed_steps = [*state.completed_steps, "review"]
    state.answers = {
        **(state.answers or {}),
        "launch": {
            "status": "queued",
            "queued_at": now.isoformat(),
            "site_id": str(site.id),
        },
    }
    await db.commit()
    await db.refresh(state)
    return state
