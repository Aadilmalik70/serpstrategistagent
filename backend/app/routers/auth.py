from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.identity import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    OAuthExchangeRequest,
    OAuthLinkConfirmRequest,
    OAuthLinkRequiredResponse,
    OAuthProviderSummary,
    RegisterRequest,
)
from app.services.auth_service import (
    AuthenticationError,
    RegistrationError,
    authenticate_user,
    create_access_token,
    list_user_workspaces,
    register_user,
    workspace_summary,
)
from app.services.oauth_service import (
    OAuthAuthenticated,
    OAuthLinkRequired,
    OAuthServiceError,
    confirm_oauth_link,
    exchange_oauth_identity,
    list_oauth_providers,
    verify_oauth_bridge_signature,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_response(result: OAuthAuthenticated) -> AuthResponse:
    token, expires_in = create_access_token(result.user)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=result.user,
        workspace=workspace_summary(result.workspace, result.membership),
    )


def _oauth_error(exc: OAuthServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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


@router.post(
    "/oauth/exchange",
    response_model=AuthResponse | OAuthLinkRequiredResponse,
)
async def oauth_exchange(
    data: OAuthExchangeRequest,
    bridge_timestamp: str = Header(alias="X-OAuth-Bridge-Timestamp"),
    bridge_signature: str = Header(alias="X-OAuth-Bridge-Signature"),
    db: AsyncSession = Depends(get_db),
) -> AuthResponse | OAuthLinkRequiredResponse:
    try:
        verify_oauth_bridge_signature(
            data,
            timestamp=bridge_timestamp,
            signature=bridge_signature,
        )
        result = await exchange_oauth_identity(db, data)
    except OAuthServiceError as exc:
        raise _oauth_error(exc) from exc

    if isinstance(result, OAuthLinkRequired):
        return OAuthLinkRequiredResponse(
            link_token=result.token,
            email=result.email,
            expires_in=result.expires_in,
        )
    return _auth_response(result)


@router.post("/oauth/link", response_model=AuthResponse)
async def oauth_link(
    data: OAuthLinkConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    try:
        result = await confirm_oauth_link(db, token=data.token, password=data.password)
    except OAuthServiceError as exc:
        raise _oauth_error(exc) from exc
    return _auth_response(result)


@router.get("/providers", response_model=list[OAuthProviderSummary])
async def providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OAuthProviderSummary]:
    return await list_oauth_providers(db, current_user.id)


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    return MeResponse(
        user=current_user,
        workspaces=await list_user_workspaces(db, current_user.id),
    )
