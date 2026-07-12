import uuid

from pydantic import BaseModel, Field


class GitHubAppStartRequest(BaseModel):
    site_id: uuid.UUID


class GitHubAppStartResponse(BaseModel):
    installation_url: str


class GitHubAppRepository(BaseModel):
    installation_record_id: uuid.UUID
    installation_id: int
    account_login: str
    full_name: str
    private: bool
    default_branch: str | None = None


class GitHubAppRepositoryCatalog(BaseModel):
    configured: bool
    repositories: list[GitHubAppRepository]


class GitHubAppRepositorySelectRequest(BaseModel):
    site_id: uuid.UUID
    installation_record_id: uuid.UUID
    repository: str = Field(min_length=3, max_length=255)


class GitHubAppSiteStatus(BaseModel):
    configured: bool
    installed: bool
    site_id: uuid.UUID
    repository: str | None
    installation_record_id: uuid.UUID | None
    account_login: str | None
    execution_ready: bool
