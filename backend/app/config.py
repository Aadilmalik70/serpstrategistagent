from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/serpstrategist"

    # Auth
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # LLM
    google_api_key: str = ""
    groq_api_key: str = ""

    # SERP Research (get free key at https://serper.dev)
    serper_api_key: str = ""

    # WordPress Integration (optional - for auto-fixing blog posts)
    wordpress_url: str = ""  # e.g. https://serpstrategists.com/wp-json
    wordpress_user: str = ""
    wordpress_app_password: str = ""

    # LibreCrawl MCP
    librecrawl_host: str = "127.0.0.1"
    librecrawl_port: int = 5080  # LibreCrawl Flask app (Docker)
    librecrawl_mcp_port: int = 5081  # MCP server (PM2)
    librecrawl_enabled: bool = True

    # App
    app_env: str = "development"
    debug: bool = True
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
