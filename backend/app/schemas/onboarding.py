from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, field_validator


ONBOARDING_STEPS = ("profile", "site", "cms", "google", "goals", "review")


class OnboardingStateResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    version: int
    current_step: str
    completed_steps: list[str]
    data: dict[str, Any]
    status: str
    started_at: datetime
    completed_at: datetime | None
    updated_at: datetime


class OnboardingStepUpdate(BaseModel):
    step: Literal["profile", "site", "cms", "google", "goals", "review"]
    data: dict[str, Any] = Field(default_factory=dict)
    complete_step: bool = True
    next_step: Literal["profile", "site", "cms", "google", "goals", "review"] | None = None


class OnboardingCompleteRequest(BaseModel):
    launch_operator: bool = True


class GoogleConnectStartRequest(BaseModel):
    return_path: str = "/onboarding/google"

    @field_validator("return_path")
    @classmethod
    def validate_return_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/") or normalized.startswith("//"):
            raise ValueError("return_path must be an application-relative path")
        return normalized


class GoogleConnectStartResponse(BaseModel):
    authorization_url: str


class GoogleConnectionResponse(BaseModel):
    id: uuid.UUID
    google_email: str
    status: str
    granted_scopes: list[str]
    selected_gsc_property: str | None
    selected_ga4_property: str | None
    selected_ga4_property_name: str | None
    connected_at: datetime
    updated_at: datetime


class GooglePropertyOption(BaseModel):
    id: str
    name: str
    kind: str
    permission_level: str | None = None
    account_name: str | None = None


class GooglePropertySelection(BaseModel):
    gsc_property: str | None = None
    ga4_property: str | None = None
    ga4_property_name: str | None = None
