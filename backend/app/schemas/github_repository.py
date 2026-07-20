import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


class GitHubRepositoryConnectRequest(BaseModel):
    site_id: uuid.UUID
    repository: str | None = Field(default=None, min_length=3, max_length=255)
    installation_id: uuid.UUID | None = None
    repository_id: int | None = Field(default=None, gt=0)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().strip("/")
        if normalized.startswith("https://github.com/"):
            normalized = normalized.removeprefix("https://github.com/").strip("/")
        parts = normalized.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("Repository must use the owner/repository format")
        return normalized

    @model_validator(mode="after")
    def validate_source(self) -> "GitHubRepositoryConnectRequest":
        public_mapping = self.repository is not None
        app_mapping = self.installation_id is not None or self.repository_id is not None
        if public_mapping == app_mapping:
            raise ValueError(
                "Provide either a public repository or both installation_id and repository_id"
            )
        if app_mapping and (self.installation_id is None or self.repository_id is None):
            raise ValueError("Authorized mappings require both installation_id and repository_id")
        return self


class GitHubRepositoryResponse(BaseModel):
    site_id: uuid.UUID
    repository: str | None
    connected: bool
    visibility: str | None = None
    default_branch: str | None = None
    installation_id: uuid.UUID | None = None
    repository_id: int | None = None
    authorization_source: str = "public"
    authorization_ready: bool = False
    execution_ready: bool = False
    patch_planning_ready: bool = False
