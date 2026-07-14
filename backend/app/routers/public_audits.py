from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.free_audit import FreeAuditCreate, FreeAuditResponse
from app.services.free_audit_service import (
    FreeAuditServiceError,
    audit_response,
    create_free_audit,
    execute_free_audit,
    get_free_audit,
    requester_fingerprint,
)

router = APIRouter(prefix="/public/audits", tags=["public-audits"])


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


@router.post("", response_model=FreeAuditResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_free_audit(
    data: FreeAuditCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FreeAuditResponse:
    try:
        audit = await create_free_audit(
            db,
            data,
            requester_hash=requester_fingerprint(_request_ip(request)),
            user_agent=request.headers.get("user-agent"),
        )
    except FreeAuditServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if audit.status in {"queued", "failed"}:
        background_tasks.add_task(execute_free_audit, audit.id)
    return audit_response(audit)


@router.get("/{token}", response_model=FreeAuditResponse)
async def read_free_audit(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> FreeAuditResponse:
    if len(token) < 20 or len(token) > 64:
        raise HTTPException(status_code=404, detail="Audit not found")
    audit = await get_free_audit(db, token)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit_response(audit)
