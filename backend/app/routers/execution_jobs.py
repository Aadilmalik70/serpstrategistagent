import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.execution import (
    ExecutionAttemptResponse,
    ExecutionEnqueueRequest,
    ExecutionJobDetailResponse,
    ExecutionJobResponse,
    ExecutionSnapshotResponse,
)
from app.services.execution_service import (
    ExecutionServiceError,
    attempt_to_dict,
    enqueue_execution,
    enqueue_rollback,
    get_execution_job,
    job_to_dict,
    list_execution_jobs,
    list_execution_snapshots,
    list_job_attempts,
    request_job_cancellation,
    snapshot_to_dict,
)

job_router = APIRouter(prefix="/execution-jobs", tags=["execution-jobs"])
action_router = APIRouter(prefix="/operator-actions", tags=["operator-actions"])


def _service_error(exc: ExecutionServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@action_router.post(
    "/{action_id}/execute",
    response_model=ExecutionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_operator_action_execution(
    action_id: uuid.UUID,
    data: ExecutionEnqueueRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ExecutionJobResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        job = await enqueue_execution(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            action_id=action_id,
            expected_version=data.expected_version,
        )
    except ExecutionServiceError as exc:
        raise _service_error(exc) from exc
    return ExecutionJobResponse(**job_to_dict(job))


@action_router.post(
    "/{action_id}/rollback",
    response_model=ExecutionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_operator_action_rollback(
    action_id: uuid.UUID,
    data: ExecutionEnqueueRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ExecutionJobResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        job = await enqueue_rollback(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            action_id=action_id,
            expected_version=data.expected_version,
        )
    except ExecutionServiceError as exc:
        raise _service_error(exc) from exc
    return ExecutionJobResponse(**job_to_dict(job))


@job_router.get("", response_model=list[ExecutionJobResponse])
async def get_execution_job_queue(
    action_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionJobResponse]:
    jobs = await list_execution_jobs(
        db,
        workspace_id=context.workspace.id,
        action_id=action_id,
        status=status_filter,
        limit=limit,
    )
    return [ExecutionJobResponse(**job_to_dict(job)) for job in jobs]


@job_router.get("/{job_id}", response_model=ExecutionJobDetailResponse)
async def get_execution_job_detail(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ExecutionJobDetailResponse:
    try:
        job = await get_execution_job(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
        attempts = await list_job_attempts(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
        snapshots = await list_execution_snapshots(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
    except ExecutionServiceError as exc:
        raise _service_error(exc) from exc
    return ExecutionJobDetailResponse(
        **job_to_dict(job),
        attempts=[ExecutionAttemptResponse(**attempt_to_dict(item)) for item in attempts],
        snapshots=[ExecutionSnapshotResponse(**snapshot_to_dict(item)) for item in snapshots],
    )


@job_router.get("/{job_id}/snapshots", response_model=list[ExecutionSnapshotResponse])
async def get_execution_job_snapshots(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionSnapshotResponse]:
    try:
        await get_execution_job(db, workspace_id=context.workspace.id, job_id=job_id)
        snapshots = await list_execution_snapshots(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
    except ExecutionServiceError as exc:
        raise _service_error(exc) from exc
    return [ExecutionSnapshotResponse(**snapshot_to_dict(item)) for item in snapshots]


@job_router.post("/{job_id}/cancel", response_model=ExecutionJobResponse)
async def cancel_execution_job(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> ExecutionJobResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        job = await request_job_cancellation(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            job_id=job_id,
        )
    except ExecutionServiceError as exc:
        raise _service_error(exc) from exc
    return ExecutionJobResponse(**job_to_dict(job))
