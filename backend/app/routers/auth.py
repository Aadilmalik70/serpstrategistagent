from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.identity import User
from app.schemas.auth import AuthResponse, LoginRequest, MeResponse, RegisterRequest
from app.services.auth_service import (
    AuthenticationError,
    RegistrationError,
    authenticate_user,
    create_access_token,
    list_user_workspaces,
    register_user,
    workspace_summary,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        user, workspace, membership = await register_user(db, data)
    except RegistrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    token, expires_in = create_access_token(user)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=user,
        workspace=workspace_summary(workspace, membership),
    )


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        user, membership, workspace = await authenticate_user(db, data.email, data.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token, expires_in = create_access_token(user)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=user,
        workspace=workspace_summary(workspace, membership),
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    return MeResponse(
        user=current_user,
        workspaces=await list_user_workspaces(db, current_user.id),
    )
