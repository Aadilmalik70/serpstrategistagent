from functools import lru_cache

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database and cache
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/serpstrategist"
    redis_url: str = ""

    # Auth
    secret_key: str = "change-me-in-production"
    oauth_bridge_secret: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # LLM providers
    openai_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""

    # Search providers
    serpapi_api_key: str = ""
    serper_api_key: str = ""

    # WordPress integration (optional)
    wordpress_url: str = ""
    wordpress_user: str = ""
    wordpress_app_password: str = ""

    # Legacy LibreCrawl adapter. Disabled by default while the first-party crawler is built.
    librecrawl_host: str = "127.0.0.1"
    librecrawl_port: int = 5080
    librecrawl_mcp_port: int = 5081
    librecrawl_enabled: bool = False

    # App runtime
    app_env: str = "development"
    debug: bool = True
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = ""
    scheduler_enabled: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Convert Railway's PostgreSQL URL to SQLAlchemy's asyncpg dialect."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def validate_secure_environment(self) -> "Settings":
        if self.app_env.lower() in {"staging", "production"}:
            if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in staging and production")
            if not self.frontend_url.startswith(("http://", "https://")):
                raise ValueError("FRONTEND_URL must be an absolute URL")
        if self.oauth_bridge_secret and len(self.oauth_bridge_secret) < 32:
            raise ValueError("OAUTH_BRIDGE_SECRET must be at least 32 characters when configured")
        return self

    @computed_field
    @property
    def allowed_origins(self) -> list[str]:
        configured = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys([self.frontend_url, *configured]))

    model_config = {"env_file": ".env", "extra": "ignore", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
