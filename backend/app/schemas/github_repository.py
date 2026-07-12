import uuid

from pydantic import BaseModel, Field, field_validator


class GitHubRepositoryConnectRequest(BaseModel):
    site_id: uuid.UUID
    repository: str = Field(min_length=3, max_length=255)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized.startswith("https://github.com/"):
            normalized = normalized.removeprefix("https://github.com/").strip("/")
        parts = normalized.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("Repository must use the owner/repository format")
        return normalized


class GitHubRepositoryResponse(BaseModel):
    site_id: uuid.UUID
    repository: str | None
    connected: bool
    visibility: str | None = None
    default_branch: str | None = None
    execution_ready: bool = False
