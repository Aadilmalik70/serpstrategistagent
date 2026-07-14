import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.operator_action import (
    ActionDecisionRequest,
    ActionTransitionRequest,
    OperatorActionCreate,
    OperatorActionDetailResponse,
    OperatorActionEventResponse,
    OperatorActionQueueResponse,
    OperatorActionResponse,
)
from app.services.operator_action_service import (
    OperatorActionServiceError,
    action_to_dict,
    cancel_action,
    create_action,
    decide_action,
    event_to_dict,
    get_action,
    list_actions,
    list_events,
    propose_action,
)

router = APIRouter(prefix="/operator-actions", tags=["operator-actions"])


def _service_error(exc: OperatorActionServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("", response_model=OperatorActionResponse, status_code=status.HTTP_201_CREATED)
async def create_operator_action(
    data: OperatorActionCreate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        action = await create_action(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            data=data,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return OperatorActionResponse(**action_to_dict(action))


@router.get("", response_model=OperatorActionQueueResponse)
async def get_operator_action_queue(
    site_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    risk_level: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionQueueResponse:
    items, counts_by_status, counts_by_risk = await list_actions(
        db,
        workspace_id=context.workspace.id,
        site_id=site_id,
        status=status_filter,
        risk_level=risk_level,
        limit=limit,
    )
    return OperatorActionQueueResponse(
        items=[OperatorActionResponse(**action_to_dict(item)) for item in items],
        total=sum(counts_by_status.values()),
        counts_by_status=counts_by_status,
        counts_by_risk=counts_by_risk,
    )


@router.get("/{action_id}", response_model=OperatorActionDetailResponse)
async def get_operator_action_detail(
    action_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionDetailResponse:
    try:
        action = await get_action(db, context.workspace.id, action_id)
        events = await list_events(
            db,
            workspace_id=context.workspace.id,
            action_id=action_id,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return OperatorActionDetailResponse(
        **action_to_dict(action),
        events=[OperatorActionEventResponse(**event_to_dict(event)) for event in events],
    )


@router.get("/{action_id}/events", response_model=list[OperatorActionEventResponse])
async def get_operator_action_events(
    action_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[OperatorActionEventResponse]:
    try:
        events = await list_events(
            db,
            workspace_id=context.workspace.id,
            action_id=action_id,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return [OperatorActionEventResponse(**event_to_dict(event)) for event in events]


@router.post("/{action_id}/propose", response_model=OperatorActionResponse)
async def propose_operator_action(
    action_id: uuid.UUID,
    data: ActionTransitionRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        action = await propose_action(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            action_id=action_id,
            expected_version=data.expected_version,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return OperatorActionResponse(**action_to_dict(action))


@router.post("/{action_id}/decision", response_model=OperatorActionResponse)
async def decide_operator_action(
    action_id: uuid.UUID,
    data: ActionDecisionRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        action = await decide_action(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            user_role=context.membership.role,
            action_id=action_id,
            expected_version=data.expected_version,
            decision=data.decision,
            reason=data.reason,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return OperatorActionResponse(**action_to_dict(action))


@router.post("/{action_id}/cancel", response_model=OperatorActionResponse)
async def cancel_operator_action(
    action_id: uuid.UUID,
    data: ActionTransitionRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> OperatorActionResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        action = await cancel_action(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            action_id=action_id,
            expected_version=data.expected_version,
        )
    except OperatorActionServiceError as exc:
        raise _service_error(exc) from exc
    return OperatorActionResponse(**action_to_dict(action))
