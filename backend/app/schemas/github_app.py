import uuid
from datetime import datetime

from pydantic import BaseModel


class GitHubAppStartResponse(BaseModel):
    installation_url: str


class GitHubAppInstallationResponse(BaseModel):
    id: uuid.UUID
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    permissions: dict
    status: str
    last_verified_at: datetime
    created_at: datetime


class GitHubAppStatusResponse(BaseModel):
    configured: bool
    connected: bool
    execution_enabled: bool = False
    installations: list[GitHubAppInstallationResponse]


class GitHubAuthorizedRepositoryResponse(BaseModel):
    installation_id: uuid.UUID
    repository_id: int
    full_name: str
    private: bool
    visibility: str
    default_branch: str | None
    permissions: dict


class GitHubAuthorizedRepositoryListResponse(BaseModel):
    items: list[GitHubAuthorizedRepositoryResponse]
    total: int
