from datetime import datetime
from pydantic import BaseModel, Field


class GoogleDataConnectionResponse(BaseModel):
    status: str
    google_email: str | None
    scopes: list[str]
    gsc_property: str | None
    ga4_property_id: str | None
    ga4_property_name: str | None
    connected_at: datetime | None
    last_refreshed_at: datetime | None
    last_error: str | None


class GoogleOAuthStartResponse(BaseModel):
    authorization_url: str


class GooglePropertyOption(BaseModel):
    id: str
    name: str
    type: str
    permission_level: str | None = None


class GooglePropertyCatalogResponse(BaseModel):
    gsc_properties: list[GooglePropertyOption]
    ga4_properties: list[GooglePropertyOption]


class GooglePropertySelectionRequest(BaseModel):
    gsc_property: str | None = Field(default=None, max_length=2048)
    ga4_property_id: str | None = Field(default=None, max_length=128)
    ga4_property_name: str | None = Field(default=None, max_length=255)
