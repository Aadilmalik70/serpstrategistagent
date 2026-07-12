from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


BillingPlan = Literal["audit", "growth", "scale"]
PaidBillingPlan = Literal["growth", "scale"]


class BillingPlanDefinition(BaseModel):
    id: BillingPlan
    name: str
    description: str
    entitlements: dict[str, int]
    checkout_available: bool


class BillingCheckoutRequest(BaseModel):
    plan: PaidBillingPlan


class BillingCheckoutConfirmRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=255)


class BillingUrlResponse(BaseModel):
    url: str


class UsageMetricSummary(BaseModel):
    used: int
    limit: int


class BillingSummary(BaseModel):
    plan: BillingPlan
    status: str
    cancel_at_period_end: bool
    current_period_start: datetime
    current_period_end: datetime
    entitlements: dict[str, int]
    usage: dict[str, UsageMetricSummary]
    stripe_customer: bool
    stripe_configured: bool


class StripeWebhookResponse(BaseModel):
    received: bool
    processed: bool
