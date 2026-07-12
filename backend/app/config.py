from functools import lru_cache
from urllib.parse import urlparse

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/serpstrategist"
    redis_url: str = ""

    secret_key: str = "change-me-in-production"
    oauth_bridge_secret: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    ai_gateway_base_url: str = "https://api.17.wtf/v1"
    ai_gateway_api_key: str = ""
    ai_primary_model: str = "posiden/deepseek-v4-flash"
    ai_reasoning_model: str = "zeus/claude-sonnet-4-6"
    ai_fallback_model: str = "latina/gpt-5.6-terra"
    ai_secondary_fallback_model: str = "latina/gpt-5.6-luna"
    ai_gateway_timeout_seconds: float = 30.0

    serpapi_api_key: str = ""
    serpapi_base_url: str = "https://serpapi.com/search.json"
    serpapi_timeout_seconds: float = 20.0

    stripe_api_base_url: str = "https://api.stripe.com/v1"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_growth_price_id: str = ""
    stripe_scale_price_id: str = ""
    stripe_timeout_seconds: float = 20.0

    # Incremental Google authorization for GSC and GA4. These are server-only.
    google_integration_client_id: str = ""
    google_integration_client_secret: str = ""
    google_integration_redirect_uri: str = ""
    google_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    google_search_console_api_url: str = "https://www.googleapis.com/webmasters/v3"
    google_analytics_admin_api_url: str = "https://analyticsadmin.googleapis.com/v1beta"
    google_integration_timeout_seconds: float = 20.0

    wordpress_url: str = ""
    wordpress_user: str = ""
    wordpress_app_password: str = ""

    librecrawl_host: str = "127.0.0.1"
    librecrawl_port: int = 5080
    librecrawl_mcp_port: int = 5081
    librecrawl_enabled: bool = False

    app_env: str = "development"
    debug: bool = True
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = ""
    scheduler_enabled: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator(
        "ai_gateway_base_url",
        "serpapi_base_url",
        "stripe_api_base_url",
        "google_oauth_authorize_url",
        "google_oauth_token_url",
        "google_userinfo_url",
        "google_search_console_api_url",
        "google_analytics_admin_api_url",
    )
    @classmethod
    def normalize_provider_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider base URLs must be absolute HTTP or HTTPS URLs")
        if parsed.username or parsed.password:
            raise ValueError("Provider base URLs cannot contain embedded credentials")
        return normalized

    @model_validator(mode="after")
    def validate_secure_environment(self) -> "Settings":
        if self.app_env.lower() in {"staging", "production"}:
            if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in staging and production")
            if not self.frontend_url.startswith(("http://", "https://")):
                raise ValueError("FRONTEND_URL must be an absolute URL")
        if self.oauth_bridge_secret and len(self.oauth_bridge_secret) < 32:
            raise ValueError("OAUTH_BRIDGE_SECRET must be at least 32 characters when configured")
        if (
            self.ai_gateway_timeout_seconds <= 0
            or self.serpapi_timeout_seconds <= 0
            or self.stripe_timeout_seconds <= 0
            or self.google_integration_timeout_seconds <= 0
        ):
            raise ValueError("Provider timeouts must be greater than zero")
        if self.stripe_secret_key and not self.stripe_secret_key.startswith(("sk_test_", "sk_live_")):
            raise ValueError("STRIPE_SECRET_KEY must be a Stripe secret key")
        if self.stripe_webhook_secret and not self.stripe_webhook_secret.startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET must be a Stripe webhook signing secret")
        if self.google_integration_redirect_uri:
            parsed = urlparse(self.google_integration_redirect_uri)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("GOOGLE_INTEGRATION_REDIRECT_URI must be an absolute URL")
        return self

    @computed_field
    @property
    def allowed_origins(self) -> list[str]:
        configured = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys([self.frontend_url, *configured]))

    @computed_field
    @property
    def stripe_price_plan_map(self) -> dict[str, str]:
        return {
            price_id: plan
            for price_id, plan in (
                (self.stripe_growth_price_id, "growth"),
                (self.stripe_scale_price_id, "scale"),
            )
            if price_id
        }

    model_config = {"env_file": ".env", "extra": "ignore", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
