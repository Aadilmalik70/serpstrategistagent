from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


ActionStatus = Literal[
    "draft",
    "needs_approval",
    "approved",
    "rejected",
    "blocked",
    "execution_queued",
    "executing",
    "validating",
    "succeeded",
    "failed",
    "rollback_queued",
    "rolling_back",
    "cancelled",
    "rolled_back",
]


class OperatorActionCreate(BaseModel):
    site_id: uuid.UUID
    issue_id: uuid.UUID | None = None
    action_type: str = Field(min_length=2, max_length=64)
    category: str = Field(default="technical", min_length=2, max_length=64)
    source: str = Field(default="operator", min_length=2, max_length=64)
    title: str = Field(min_length=3, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    plan: dict[str, Any] = Field(default_factory=dict)
    impact_score: int = Field(default=0, ge=0, le=100)
    confidence_score: int = Field(default=0, ge=0, le=100)
    effort_score: int = Field(default=0, ge=0, le=100)
    risk_score: int = Field(default=0, ge=0, le=100)
    execution_target: dict[str, Any] = Field(default_factory=dict)
    proposed_diff: dict[str, Any] = Field(default_factory=dict)
    rollback_plan: dict[str, Any] = Field(default_factory=dict)
    measurement_plan: dict[str, Any] = Field(default_factory=dict)
    validation_checklist: list[dict[str, Any] | str] = Field(default_factory=list, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("action_type", "category", "source", "title")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be empty")
        return normalized

    @model_validator(mode="after")
    def require_governance_material(self) -> "OperatorActionCreate":
        if not self.evidence:
            raise ValueError("At least one evidence item is required")
        if not self.plan:
            raise ValueError("A structured action plan is required")
        if not self.rollback_plan:
            raise ValueError("A rollback plan is required")
        if not self.measurement_plan:
            raise ValueError("A measurement plan is required")
        if not self.validation_checklist:
            raise ValueError("A validation checklist is required")
        return self


class ActionTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ActionDecisionRequest(ActionTransitionRequest):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def rejection_requires_reason(self) -> "ActionDecisionRequest":
        if self.decision == "reject" and not (self.reason or "").strip():
            raise ValueError("A rejection reason is required")
        return self


class OperatorActionEventResponse(BaseModel):
    id: uuid.UUID
    action_id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_user_id: uuid.UUID | None
    actor_type: str
    payload: dict[str, Any]
    created_at: datetime


class OperatorActionResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    site_id: uuid.UUID
    issue_id: uuid.UUID | None
    action_type: str
    category: str
    source: str
    status: str
    title: str
    description: str | None
    evidence: list[dict[str, Any]]
    plan: dict[str, Any]
    impact_score: int
    confidence_score: int
    effort_score: int
    risk_score: int
    risk_level: str
    approval_policy: dict[str, Any]
    requires_approval: bool
    execution_target: dict[str, Any]
    proposed_diff: dict[str, Any]
    rollback_plan: dict[str, Any]
    measurement_plan: dict[str, Any]
    validation_checklist: list[Any]
    execution_result: dict[str, Any] | None
    idempotency_key: str | None
    version: int
    created_by_user_id: uuid.UUID | None
    approved_by_user_id: uuid.UUID | None
    rejected_by_user_id: uuid.UUID | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    proposed_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    execution_started_at: datetime | None
    executed_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None


class OperatorActionDetailResponse(OperatorActionResponse):
    events: list[OperatorActionEventResponse]


class OperatorActionQueueResponse(BaseModel):
    items: list[OperatorActionResponse]
    total: int
    counts_by_status: dict[str, int]
    counts_by_risk: dict[str, int]
