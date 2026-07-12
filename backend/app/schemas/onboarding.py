from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, field_validator


ONBOARDING_STEPS = ["profile", "site", "cms", "google", "goals", "review"]


class OnboardingStepUpdate(BaseModel):
    step: Literal["profile", "site", "cms", "google", "goals", "review"]
    answers: dict[str, Any] = Field(default_factory=dict)
    complete_step: bool = True
    next_step: Literal["profile", "site", "cms", "google", "goals", "review"] | None = None

    @field_validator("answers")
    @classmethod
    def limit_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(str(value)) > 50_000:
            raise ValueError("Onboarding payload is too large")
        return value


class OnboardingCompleteRequest(BaseModel):
    launch_operator: bool = True


class OnboardingResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    onboarding_version: int
    current_step: str
    completed_steps: list[str]
    answers: dict[str, Any]
    status: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    completion_percent: int
