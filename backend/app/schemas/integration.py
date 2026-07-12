from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, Field, field_validator


SUPPORTED_MANUAL_PROVIDERS = {"openai", "gemini", "serpapi", "serper", "wordpress"}
SUPPORTED_PROVIDER_IDS = SUPPORTED_MANUAL_PROVIDERS | {"google_search_console", "google_analytics"}


class IntegrationFieldDefinition(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool = True
    placeholder: str | None = None
    help_text: str | None = None


class IntegrationProviderDefinition(BaseModel):
    id: str
    name: str
    description: str
    connection_mode: str
    scope: str
    available: bool
    test_supported: bool
    fields: list[IntegrationFieldDefinition]


class IntegrationCredentialCreate(BaseModel):
    provider: str
    label: str = Field(min_length=2, max_length=255)
    site_id: uuid.UUID | None = None
    external_account_id: str = Field(default="default", min_length=1, max_length=255)
    credentials: dict[str, Any]

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_MANUAL_PROVIDERS:
            raise ValueError("This provider does not support manual credential storage")
        return normalized

    @field_validator("label", "external_account_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be empty")
        return normalized


class IntegrationCredentialRotate(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=255)
    credentials: dict[str, Any]

    @field_validator("label")
    @classmethod
    def normalize_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class IntegrationCredentialResponse(BaseModel):
    id: uuid.UUID
    provider: str
    provider_name: str
    label: str
    site_id: uuid.UUID | None
    scope: str
    external_account_id: str
    status: str
    metadata: dict[str, Any]
    last_validation_status: str
    last_validation_error: str | None
    last_validated_at: datetime | None
    rotated_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    test_supported: bool


class IntegrationCredentialTestResponse(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    message: str
    tested_at: datetime
