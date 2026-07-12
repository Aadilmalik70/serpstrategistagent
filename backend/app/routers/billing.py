from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.billing import (
    BillingCheckoutRequest,
    BillingPlanDefinition,
    BillingSummary,
    BillingUrlResponse,
    StripeWebhookResponse,
)
from app.services.billing_service import (
    StripeBillingError,
    billing_summary,
    create_billing_portal_session,
    create_checkout_session,
    parse_and_process_webhook,
)
from app.services.entitlement_service import get_plan_entitlements


router = APIRouter(prefix="/billing", tags=["billing"])


PLAN_COPY = {
    "audit": (
        "Audit",
        "Evaluate one site with starter crawl, AI, and live SERP allowances.",
    ),
    "growth": (
        "Growth",
        "Operate multiple client sites with higher monthly crawl and intelligence capacity.",
    ),
    "scale": (
        "Scale",
        "Run an agency or larger portfolio with expanded team and provider quotas.",
    ),
}


def _billing_error(exc: StripeBillingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/plans", response_model=list[BillingPlanDefinition])
async def list_plans(
    context: WorkspaceContext = Depends(get_current_workspace),
) -> list[BillingPlanDefinition]:
    del context
    return [
        BillingPlanDefinition(
            id=plan,
            name=PLAN_COPY[plan][0],
            description=PLAN_COPY[plan][1],
            entitlements=get_plan_entitlements(plan),
            checkout_available=plan in {"growth", "scale"},
        )
        for plan in ("audit", "growth", "scale")
    ]


@router.get("/summary", response_model=BillingSummary)
async def get_billing_summary(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> BillingSummary:
    return BillingSummary.model_validate(await billing_summary(db, context.workspace.id))


@router.post("/checkout", response_model=BillingUrlResponse)
async def start_checkout(
    data: BillingCheckoutRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> BillingUrlResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        url = await create_checkout_session(
            db,
            workspace_id=context.workspace.id,
            plan=data.plan,
            email=context.user.email,
            name=context.user.name,
        )
    except StripeBillingError as exc:
        raise _billing_error(exc) from exc
    return BillingUrlResponse(url=url)


@router.post("/portal", response_model=BillingUrlResponse)
async def start_billing_portal(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> BillingUrlResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        url = await create_billing_portal_session(db, workspace_id=context.workspace.id)
    except StripeBillingError as exc:
        raise _billing_error(exc) from exc
    return BillingUrlResponse(url=url)


@router.post("/webhook", response_model=StripeWebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> StripeWebhookResponse:
    payload = await request.body()
    try:
        processed = await parse_and_process_webhook(
            db,
            payload=payload,
            signature_header=stripe_signature,
        )
    except StripeBillingError as exc:
        raise _billing_error(exc) from exc
    return StripeWebhookResponse(received=True, processed=processed)
