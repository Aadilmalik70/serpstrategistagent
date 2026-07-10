from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.site import (
    SiteClaimStartResponse,
    SiteClaimVerifyRequest,
    SiteDomainRequest,
    SiteResponse,
)
from app.services.site_claim_service import (
    SiteClaimError,
    start_site_claim,
    verification_record_name,
    verify_and_complete_site_claim,
)

router = APIRouter(prefix="/sites/claims", tags=["site-claims"])


def _claim_http_error(error: SiteClaimError) -> HTTPException:
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    if error.code == "site_not_found":
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        "already_owned",
        "domain_unavailable",
        "claim_in_progress",
        "claim_unavailable",
    }:
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post("/start", response_model=SiteClaimStartResponse)
async def start_claim(
    data: SiteDomainRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SiteClaimStartResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        site, token, expires_at = await start_site_claim(
            db,
            domain=data.domain,
            workspace_id=context.workspace.id,
        )
    except SiteClaimError as error:
        raise _claim_http_error(error) from error

    return SiteClaimStartResponse(
        site_id=site.id,
        domain=site.domain,
        method="dns_txt",
        record_name=verification_record_name(site.domain),
        record_value=token,
        expires_at=expires_at,
    )


@router.post("/verify", response_model=SiteResponse)
async def verify_claim(
    data: SiteClaimVerifyRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        return await verify_and_complete_site_claim(
            db,
            domain=data.domain,
            workspace_id=context.workspace.id,
            token=data.token,
        )
    except SiteClaimError as error:
        raise _claim_http_error(error) from error
