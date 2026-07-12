from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    workspace_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("name", "workspace_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class OAuthExchangeRequest(BaseModel):
    provider: Literal["google", "github"]
    provider_account_id: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    email_verified: bool
    name: str | None = Field(default=None, max_length=255)
    image_url: str | None = Field(default=None, max_length=2048)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("provider_account_id")
    @classmethod
    def normalize_provider_account_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Provider account ID is required")
        return normalized

    @field_validator("name", "image_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OAuthLinkConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=1, max_length=128)


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Workspace name must contain at least two characters")
        return normalized


class WorkspaceInvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "member"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"admin", "member"}:
            raise ValueError("Invitation role must be admin or member")
        return value


class WorkspaceInvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class MembershipRoleUpdateRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"owner", "admin", "member"}:
            raise ValueError("Membership role must be owner, admin, or member")
        return value


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    image_url: str | None
    status: str
    created_at: datetime


class WorkspaceSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str
    status: str


class WorkspaceMemberSummary(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str | None
    role: str
    status: str
    joined_at: datetime


class WorkspaceInvitationSummary(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class WorkspaceInvitationCreated(WorkspaceInvitationSummary):
    accept_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserSummary
    workspace: WorkspaceSummary


class OAuthLinkRequiredResponse(BaseModel):
    link_required: Literal[True] = True
    link_token: str
    email: str
    expires_in: int


class OAuthProviderSummary(BaseModel):
    provider: str
    email: str
    linked_at: datetime
    last_login_at: datetime


class MeResponse(BaseModel):
    user: UserSummary
    workspaces: list[WorkspaceSummary]
